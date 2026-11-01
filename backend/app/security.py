import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.models import AdminSession, AdminUser, AuditLog

# Argon2id con parámetros por encima de los mínimos recomendados por OWASP.
_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15

# Hash ficticio para igualar tiempos cuando el usuario no existe.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < 12:
        problems.append("debe tener al menos 12 caracteres")
    if len(password) > 128:
        problems.append("no puede superar los 128 caracteres")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        problems.append("debe combinar letras y números")
    return problems


def keyed_hash(value: str) -> str:
    """Hash HMAC-SHA256 con la clave del servidor: no reversible y no comparable entre instalaciones."""
    return hmac.new(get_settings().secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def create_session(db: Session, admin: AdminUser, ip: str | None, user_agent: str | None) -> tuple[str, AdminSession]:
    settings = get_settings()
    now = utcnow()
    db.execute(delete(AdminSession).where(AdminSession.expires_at < now))
    token = new_token()
    session = AdminSession(
        admin_id=admin.id,
        token_hash=keyed_hash(token),
        csrf_token=secrets.token_urlsafe(24),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_ttl_hours),
        ip_hash=keyed_hash(ip) if ip else None,
        user_agent=(user_agent or "")[:255] or None,
    )
    db.add(session)
    db.flush()
    return token, session


def resolve_session(db: Session, token: str | None) -> AdminSession | None:
    if not token or len(token) > 100:
        return None
    session = db.scalar(select(AdminSession).where(AdminSession.token_hash == keyed_hash(token)))
    if session is None:
        return None
    now = utcnow()
    if session.expires_at <= now or not session.admin.is_active:
        db.delete(session)
        db.commit()
        return None
    if (now - session.last_seen_at).total_seconds() > 60:
        session.last_seen_at = now
        db.commit()
    return session


def audit(
    db: Session,
    actor_type: str,
    action: str,
    *,
    actor_id: int | None = None,
    entity: str | None = None,
    entity_id: int | None = None,
    details: dict | None = None,
) -> None:
    """Registro de auditoría. Nunca debe recibir contraseñas, tokens ni datos personales completos."""
    db.add(
        AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity=entity,
            entity_id=entity_id,
            details=details or {},
        )
    )
