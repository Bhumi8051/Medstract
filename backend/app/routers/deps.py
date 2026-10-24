"""Shared dependencies for account routes: current user, login requirement, CSRF check."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.db_models import User
from app.services.auth import LoginThrottle, user_for_token

CSRF_HEADER = "X-Requested-With"
CSRF_HEADER_VALUE = "fetch"

DB = Annotated[AsyncSession, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


async def current_user_optional(request: Request, db: DB, settings: AppSettings) -> User | None:
    return await user_for_token(db, request.cookies.get(settings.session_cookie_name))


async def require_user(user: Annotated[User | None, Depends(current_user_optional)]) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Please log in to continue.")
    return user


def require_csrf_header(request: Request) -> None:
    """CSRF defence for cookie-authenticated changes.

    Browsers only let another site send a custom header after a CORS preflight,
    which our CORS allowlist refuses, so a forged cross-site form or request
    can't include it. (SameSite=Lax cookies are the first line of defence.)
    """
    if request.headers.get(CSRF_HEADER) != CSRF_HEADER_VALUE:
        raise HTTPException(status_code=403, detail=f"Missing {CSRF_HEADER} header.")


def get_login_throttle(request: Request) -> LoginThrottle:
    return request.app.state.login_throttle


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_days * 24 * 3600,
        httponly=True,  # not readable from JavaScript
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )


CurrentUser = Annotated[User, Depends(require_user)]
CSRFProtected = Depends(require_csrf_header)
