import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="sar-test-"))
os.environ.update(
    ENVIRONMENT="test",
    DATABASE_URL=f"sqlite:///{(_tmp / 'test.db').as_posix()}",
    AI_MODE="mock",
    ADMIN_SETUP_TOKEN="token-de-prueba-123",
    COOKIE_SECURE="false",
    SECRET_KEY="clave-de-pruebas-con-longitud-suficiente-0123456789",
    CORS_ORIGINS="http://testserver",
    PUBLIC_BASE_URL="http://testserver",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.ratelimit import limiter  # noqa: E402
from app.seed import seed  # noqa: E402

ADMIN_EMAIL = "propietario@example.com"
ADMIN_PASSWORD = "ClaveSegura2026"


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    limiter.reset()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_client(client):
    response = client.post(
        "/api/admin/auth/setup",
        json={"setup_token": "token-de-prueba-123", "email": ADMIN_EMAIL, "full_name": "Propietario", "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 201, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client


def start_chat(client) -> str:
    response = client.post("/api/chat/conversations", json={"consent": True, "consent_version": "2026-11"})
    assert response.status_code == 201, response.text
    return response.json()["token"]


def say(client, token: str, text: str) -> dict:
    response = client.post("/api/chat/messages", json={"message": text}, headers={"X-Conversation-Token": token})
    assert response.status_code == 200, response.text
    return response.json()
