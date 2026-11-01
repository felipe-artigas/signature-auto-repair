import hmac
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, utcnow
from app.deps import require_admin
from app.models import AdminSession, AdminUser
from app.ratelimit import client_ip, enforce
from app.security import (
    LOCKOUT_MINUTES,
    MAX_FAILED_LOGINS,
    audit,
    create_session,
    hash_password,
    keyed_hash,
    password_problems,
    verify_password,
)

router = APIRouter(prefix="/api/admin/auth", tags=["autenticación"])

INVALID_CREDENTIALS = "Correo o contraseña incorrectos."


class SetupIn(BaseModel):
    setup_token: str = Field(max_length=200)
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(max_length=128)


def _set_session_cookies(response: Response, token: str, csrf: str) -> None:
    settings = get_settings()
    max_age = settings.session_ttl_hours * 3600
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/api",
    )
    response.set_cookie(
        settings.csrf_cookie_name, csrf, max_age=max_age, httponly=False, secure=settings.cookie_secure,
        samesite="strict", path="/",
    )


def _admin_out(admin: AdminUser, csrf: str) -> dict:
    return {"id": admin.id, "email": admin.email, "full_name": admin.full_name, "csrf_token": csrf}


@router.get("/status")
def auth_status(db: Session = Depends(get_db)):
    has_admin = db.scalar(select(func.count(AdminUser.id))) > 0
    return {"setup_required": not has_admin, "setup_enabled": bool(get_settings().admin_setup_token) and not has_admin}


@router.post("/setup", status_code=201)
def setup(body: SetupIn, request: Request, response: Response, db: Session = Depends(get_db)):
    enforce(request, "admin-setup", limit=5, window_seconds=3600)
    settings = get_settings()
    if db.scalar(select(func.count(AdminUser.id))) > 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "La cuenta administrativa ya fue creada.")
    if not settings.admin_setup_token or not hmac.compare_digest(body.setup_token, settings.admin_setup_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Token de configuración inválido.")
    problems = password_problems(body.password)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "La contraseña " + ", ".join(problems) + ".")
    admin = AdminUser(email=body.email.lower(), full_name=body.full_name.strip(), password_hash=hash_password(body.password))
    db.add(admin)
    db.flush()
    token, session = create_session(db, admin, client_ip(request), request.headers.get("user-agent"))
    audit(db, "admin", "admin_setup", actor_id=admin.id, entity="admin_user", entity_id=admin.id)
    db.commit()
    _set_session_cookies(response, token, session.csrf_token)
    return _admin_out(admin, session.csrf_token)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    enforce(request, "admin-login-ip", limit=10, window_seconds=900)
    enforce(request, "admin-login-account", limit=10, window_seconds=900, key=body.email.lower())
    admin = db.scalar(select(AdminUser).where(AdminUser.email == body.email.lower()))
    now = utcnow()
    if admin and admin.locked_until and admin.locked_until > now:
        verify_password(None, body.password)  # Igualar tiempos.
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Cuenta bloqueada temporalmente por intentos fallidos.")
    if admin is None or not admin.is_active or not verify_password(admin.password_hash, body.password):
        if admin:
            admin.failed_login_attempts += 1
            if admin.failed_login_attempts >= MAX_FAILED_LOGINS:
                admin.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
                admin.failed_login_attempts = 0
                audit(db, "sistema", "admin_locked", entity="admin_user", entity_id=admin.id)
            db.commit()
        audit(db, "sistema", "login_failed", details={"ip": keyed_hash(ip)[:16]})
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID_CREDENTIALS)
    admin.failed_login_attempts = 0
    admin.locked_until = None
    admin.last_login_at = now
    token, session = create_session(db, admin, ip, request.headers.get("user-agent"))
    audit(db, "admin", "login", actor_id=admin.id)
    db.commit()
    _set_session_cookies(response, token, session.csrf_token)
    return _admin_out(admin, session.csrf_token)


@router.post("/logout")
def logout(response: Response, session: AdminSession = Depends(require_admin), db: Session = Depends(get_db)):
    db.execute(delete(AdminSession).where(AdminSession.id == session.id))
    db.commit()
    settings = get_settings()
    response.delete_cookie(settings.session_cookie_name, path="/api")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    return {"ok": True}


@router.get("/me")
def me(session: AdminSession = Depends(require_admin)):
    return _admin_out(session.admin, session.csrf_token)


@router.post("/change-password")
def change_password(
    body: PasswordChangeIn,
    request: Request,
    session: AdminSession = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce(request, "admin-password", limit=5, window_seconds=900)
    admin = db.get(AdminUser, session.admin_id)
    if not verify_password(admin.password_hash, body.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La contraseña actual no es correcta.")
    problems = password_problems(body.new_password)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "La contraseña " + ", ".join(problems) + ".")
    admin.password_hash = hash_password(body.new_password)
    # Se cierran las demás sesiones abiertas.
    db.execute(delete(AdminSession).where(AdminSession.admin_id == admin.id, AdminSession.id != session.id))
    audit(db, "admin", "password_changed", actor_id=admin.id)
    db.commit()
    return {"ok": True}
