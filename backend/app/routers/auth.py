"""Register, log in, log out, and read the current account."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db_models import ResearchPreferences, User
from app.models import AccountOut, LoginRequest, PreferencesOut, RegisterRequest, SummaryLevel, UserOut
from app.routers.deps import (
    DB,
    AppSettings,
    CSRFProtected,
    clear_session_cookie,
    client_ip,
    current_user_optional,
    get_login_ip_limiter,
    get_login_throttle,
    get_register_ip_limiter,
    set_session_cookie,
)
from app.services.auth import (
    LoginThrottle,
    SlidingWindowLimiter,
    create_session,
    delete_session,
    hash_password,
    needs_rehash,
    normalize_email,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

INVALID_LOGIN = "Incorrect email or password."
TOO_MANY_LOGINS = "Too many failed login attempts. Please wait a few minutes and try again."


def too_many(detail: str, wait: int) -> HTTPException:
    return HTTPException(status_code=429, detail=detail, headers={"Retry-After": str(wait)})


def account_out(user: User, preferences: ResearchPreferences) -> AccountOut:
    return AccountOut(
        user=UserOut(id=user.id, email=user.email, created_at=user.created_at),
        preferences=PreferencesOut(
            summary_level=SummaryLevel(preferences.summary_level),
            research_interests=list(preferences.research_interests),
        ),
    )


async def load_preferences(db: DB, user: User) -> ResearchPreferences:
    """The user's preferences row, created with defaults if it's missing."""
    preferences = await db.get(ResearchPreferences, user.id)
    if preferences is None:
        preferences = ResearchPreferences(user_id=user.id, summary_level=SummaryLevel.COLLEGE.value, research_interests=[])
        db.add(preferences)
        await db.flush()
    return preferences


@router.post("/register", status_code=201, response_model=AccountOut, dependencies=[CSRFProtected])
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    db: DB,
    settings: AppSettings,
    ip_limiter: Annotated[SlidingWindowLimiter, Depends(get_register_ip_limiter)],
) -> AccountOut:
    # Every attempt counts (including "email already exists"), so scripted sign-ups
    # and probing for registered emails are both slowed down. Checked before hashing.
    if (wait := ip_limiter.hit(client_ip(request, settings))) is not None:
        raise too_many("Too many sign-up attempts from your network. Please try again later.", wait)
    user = User(email=normalize_email(body.email), password_hash=await hash_password(body.password))
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists. Try logging in.")

    preferences = ResearchPreferences(user_id=user.id, summary_level=SummaryLevel.COLLEGE.value, research_interests=[])
    db.add(preferences)
    token, _ = await create_session(db, user, settings)
    await db.commit()
    set_session_cookie(response, token, settings)
    return account_out(user, preferences)


@router.post("/login", response_model=AccountOut, dependencies=[CSRFProtected])
async def login(
    body: LoginRequest,
    response: Response,
    db: DB,
    settings: AppSettings,
    throttle: Annotated[LoginThrottle, Depends(get_login_throttle)],
    ip_limiter: Annotated[SlidingWindowLimiter, Depends(get_login_ip_limiter)],
    request: Request,
) -> AccountOut:
    email = normalize_email(body.email)
    ip = client_ip(request, settings)
    # Two independent limits on FAILED logins: per email (guessing one account's
    # password) and per IP (one password tried against many emails).
    for wait in (throttle.retry_after(email), ip_limiter.retry_after(ip)):
        if wait is not None:
            raise too_many(TOO_MANY_LOGINS, wait)

    user = (await db.execute(select(User).where(func.lower(User.email) == email))).scalar_one_or_none()
    # Always verify (against a dummy hash for unknown emails) so timing doesn't reveal which emails exist.
    if not await verify_password(user.password_hash if user else None, body.password) or user is None:
        throttle.record_failure(email)
        ip_limiter.record(ip)
        raise HTTPException(status_code=401, detail=INVALID_LOGIN)

    # Clear this email's failures. The IP counter is NOT reset: otherwise an attacker
    # could wipe it by logging into their own account between guesses.
    throttle.reset(email)
    if needs_rehash(user.password_hash):
        user.password_hash = await hash_password(body.password)
    preferences = await load_preferences(db, user)
    token, _ = await create_session(db, user, settings)
    await db.commit()
    set_session_cookie(response, token, settings)
    return account_out(user, preferences)


@router.post("/logout", status_code=204, dependencies=[CSRFProtected])
async def logout(request: Request, response: Response, db: DB, settings: AppSettings) -> Response:
    """Ends the current session. Safe to call when not logged in."""
    await delete_session(db, request.cookies.get(settings.session_cookie_name))
    await db.commit()
    response.status_code = 204
    clear_session_cookie(response, settings)
    return response


@router.get("/me", response_model=AccountOut)
async def me(user: Annotated[User | None, Depends(current_user_optional)], db: DB) -> AccountOut:
    if user is None:
        raise HTTPException(status_code=401, detail="Not logged in.")
    preferences = await load_preferences(db, user)
    await db.commit()
    return account_out(user, preferences)
