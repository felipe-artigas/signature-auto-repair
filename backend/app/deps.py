import hmac
from datetime import datetime

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import AdminSession
from app.security import resolve_session

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") + "Z" if dt else None


def _origin_allowed(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True  # Navegadores modernos envían Origin en POST/PATCH; SameSite=Strict cubre el resto.
    settings = get_settings()
    allowed = {settings.public_base_url.rstrip("/"), *(o.rstrip("/") for o in settings.cors_origins)}
    return origin.rstrip("/") in allowed


def require_admin(request: Request, db: Session = Depends(get_db)) -> AdminSession:
    settings = get_settings()
    session = resolve_session(db, request.cookies.get(settings.session_cookie_name))
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión no válida o expirada.")
    if request.method not in SAFE_METHODS:
        header = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(header, session.csrf_token) or not _origin_allowed(request):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Solicitud rechazada por protección CSRF.")
    request.state.admin_id = session.admin_id
    return session
