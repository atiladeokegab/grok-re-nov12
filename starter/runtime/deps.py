"""FastAPI dependencies every router shares: the store and the admin token."""

import hashlib
import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from starter.core.store import Store


def session_token(password: str) -> str:
    # ponytail: one shared admin token derived from the password, valid on every instance and
    # never expiring; add per-user sessions if the demo ever has real users.
    return hmac.new(password.encode(), b"starter-session", hashlib.sha256).hexdigest()


def require_token(request: Request, authorization: str = Header("")) -> None:
    expected = session_token(request.app.state.settings.admin_password)
    if not hmac.compare_digest(authorization.removeprefix("Bearer "), expected):
        raise HTTPException(401, "login required")


def get_store(request: Request) -> Store:
    return request.app.state.store


StoreDep = Annotated[Store, Depends(get_store)]
