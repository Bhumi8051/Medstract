"""Unsubscribe links from scheduled digest emails (Step D, stage 3). No login needed.

GET  /api/unsubscribe?token=...        what the link is for; changes nothing (link
                                       scanners and previews often open links)
POST /api/unsubscribe {"token": ...}   the confirm button on /unsubscribe
POST /api/unsubscribe/one-click?token  RFC 8058 one-click, POSTed by mail apps
                                       (no cookies, no CSRF header, empty 200)

All three are idempotent. The token is the only credential, so no cookie is
read and no CSRF check applies. Malformed or unknown tokens get one generic 404,
and too many of them from one IP get 429.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.models import UnsubscribeIn, UnsubscribeOut
from app.routers.deps import DB, AppSettings, client_ip, get_utc_now
from app.services.auth import SlidingWindowLimiter
from app.services.unsubscribe import find_link, unsubscribe

router = APIRouter(prefix="/api/unsubscribe", tags=["unsubscribe"])

INVALID = "This unsubscribe link is invalid or no longer exists."


def get_unsubscribe_limiter(request: Request) -> SlidingWindowLimiter:
    return request.app.state.unsubscribe_ip_limiter


Limiter = Annotated[SlidingWindowLimiter, Depends(get_unsubscribe_limiter)]
Now = Annotated[datetime, Depends(get_utc_now)]


def check_rate(request: Request, settings: AppSettings, limiter: SlidingWindowLimiter) -> str:
    ip = client_ip(request, settings)
    if (wait := limiter.retry_after(ip)) is not None:
        raise HTTPException(
            status_code=429, detail="Too many invalid unsubscribe attempts. Please wait and try again.",
            headers={"Retry-After": str(wait)},
        )
    return ip


def invalid(limiter: SlidingWindowLimiter, ip: str) -> HTTPException:
    limiter.record(ip)  # only failures count, so real links always work
    return HTTPException(status_code=404, detail=INVALID)


@router.get("", response_model=UnsubscribeOut)
async def link_info(
    request: Request, db: DB, settings: AppSettings, limiter: Limiter, token: Annotated[str, Query(max_length=100)]
) -> UnsubscribeOut:
    ip = check_rate(request, settings, limiter)
    info = await find_link(db, token)
    if info is None:
        raise invalid(limiter, ip)
    return UnsubscribeOut(status="unsubscribed" if info.unsubscribed else "subscribed", topic=info.topic)


@router.post("", response_model=UnsubscribeOut)
async def confirm_unsubscribe(
    request: Request, body: UnsubscribeIn, db: DB, settings: AppSettings, limiter: Limiter, now: Now
) -> UnsubscribeOut:
    ip = check_rate(request, settings, limiter)
    result = await unsubscribe(db, body.token, now)
    if result is None:
        raise invalid(limiter, ip)
    info, changed = result
    return UnsubscribeOut(status="unsubscribed" if changed else "already_unsubscribed", topic=info.topic)


@router.post("/one-click", status_code=200, response_class=Response)
async def one_click_unsubscribe(
    request: Request,
    db: DB,
    settings: AppSettings,
    limiter: Limiter,
    now: Now,
    token: Annotated[str, Query(max_length=100)],
) -> Response:
    """RFC 8058. The body ("List-Unsubscribe=One-Click") isn't needed: the token is in the URL."""
    ip = check_rate(request, settings, limiter)
    if await unsubscribe(db, token, now) is None:
        raise invalid(limiter, ip)
    return Response(status_code=200)
