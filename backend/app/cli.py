"""Comandos de administración.

    python -m app.cli seed              Carga servicios y configuración inicial.
    python -m app.cli create-admin      Crea la cuenta administrativa de forma interactiva.
    python -m app.cli backup DESTINO    Copia consistente de la base SQLite.
    python -m app.cli purge             Aplica la política de retención de datos.
"""

import getpass
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, func, select

from app.config import get_settings
from app.db import SessionLocal, utcnow
from app.models import AdminSession, AdminUser, AuditLog, Conversation
from app.security import audit, hash_password, password_problems
from app.seed import seed

# Conversaciones que nunca derivaron en una solicitud se eliminan a los 180 días.
INCOMPLETE_CONVERSATION_RETENTION_DAYS = 180
AUDIT_RETENTION_DAYS = 365


def create_admin() -> None:
    with SessionLocal() as db:
        if db.scalar(select(func.count(AdminUser.id))):
            sys.exit("Ya existe una cuenta administrativa.")
        email = input("Correo electrónico: ").strip().lower()
        name = input("Nombre completo: ").strip()
        password = getpass.getpass("Contraseña: ")
        if password != getpass.getpass("Repetir contraseña: "):
            sys.exit("Las contraseñas no coinciden.")
        if problems := password_problems(password):
            sys.exit("La contraseña " + ", ".join(problems) + ".")
        admin = AdminUser(email=email, full_name=name, password_hash=hash_password(password))
        db.add(admin)
        db.flush()
        audit(db, "sistema", "admin_created_cli", entity="admin_user", entity_id=admin.id)
        db.commit()
        print("Cuenta creada.")


def backup(destination: str) -> None:
    url = get_settings().database_url
    if not url.startswith("sqlite:///"):
        sys.exit("El respaldo integrado solo aplica a SQLite.")
    source = sqlite3.connect(url.removeprefix("sqlite:///"))
    target_path = Path(destination)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target = sqlite3.connect(target_path)
    with target:
        source.backup(target)
    source.close()
    target.close()
    target_path.chmod(0o600)
    print(f"Respaldo creado: {target_path}")


def purge() -> None:
    now = utcnow()
    with SessionLocal() as db:
        old = db.scalars(
            select(Conversation).where(
                Conversation.customer_id.is_(None),
                Conversation.last_message_at < now - timedelta(days=INCOMPLETE_CONVERSATION_RETENTION_DAYS),
            )
        ).all()
        for conv in old:
            db.delete(conv)
        db.execute(delete(AdminSession).where(AdminSession.expires_at < now))
        db.execute(delete(AuditLog).where(AuditLog.created_at < now - timedelta(days=AUDIT_RETENTION_DAYS)))
        audit(db, "sistema", "retention_purge", details={"conversations": len(old)})
        db.commit()
        print(f"Conversaciones eliminadas: {len(old)}")


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "seed":
        with SessionLocal() as db:
            seed(db)
        print("Datos iniciales cargados.")
    elif command == "create-admin":
        create_admin()
    elif command == "backup" and len(sys.argv) == 3:
        backup(sys.argv[2])
    elif command == "purge":
        purge()
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
