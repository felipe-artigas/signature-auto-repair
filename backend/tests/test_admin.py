from datetime import timedelta

from sqlalchemy import select

from app.db import SessionLocal, utcnow
from app.models import AdminUser, Conversation, ServiceRequest
from app.services.availability import free_slots, to_local
from app.services.business import get_business_settings
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, say, start_chat
from tests.test_assistant import complete_intake

ADMIN_ENDPOINTS = [
    "/api/admin/dashboard", "/api/admin/requests", "/api/admin/customers", "/api/admin/vehicles",
    "/api/admin/radar", "/api/admin/services", "/api/admin/settings", "/api/admin/audit",
    "/api/admin/appointments?from=2026-01-01&to=2026-01-31",
]


def test_admin_routes_require_authentication(client):
    for path in ADMIN_ENDPOINTS:
        assert client.get(path).status_code == 401, path
    assert client.patch("/api/admin/requests/1", json={"status": "aprobado"}).status_code == 401


def test_setup_requires_token_and_runs_once(client):
    bad = client.post(
        "/api/admin/auth/setup",
        json={"setup_token": "incorrecto", "email": "x@example.com", "full_name": "Xavier", "password": ADMIN_PASSWORD},
    )
    assert bad.status_code == 403
    weak = client.post(
        "/api/admin/auth/setup",
        json={"setup_token": "token-de-prueba-123", "email": "x@example.com", "full_name": "Xavier", "password": "corta"},
    )
    assert weak.status_code == 422
    ok = client.post(
        "/api/admin/auth/setup",
        json={"setup_token": "token-de-prueba-123", "email": ADMIN_EMAIL, "full_name": "Propietario", "password": ADMIN_PASSWORD},
    )
    assert ok.status_code == 201
    again = client.post(
        "/api/admin/auth/setup",
        json={"setup_token": "token-de-prueba-123", "email": "y@example.com", "full_name": "Yanina", "password": ADMIN_PASSWORD},
    )
    assert again.status_code == 409
    with SessionLocal() as db:
        admin = db.scalar(select(AdminUser))
        assert admin.password_hash.startswith("$argon2id$")


def test_login_lockout_and_cookie_flags(admin_client):
    admin_client.post("/api/admin/auth/logout")
    admin_client.cookies.clear()
    for _ in range(5):
        assert admin_client.post("/api/admin/auth/login", json={"email": ADMIN_EMAIL, "password": "Incorrecta123"}).status_code == 401
    locked = admin_client.post("/api/admin/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert locked.status_code == 429
    with SessionLocal() as db:
        admin = db.scalar(select(AdminUser))
        admin.locked_until = None
        db.commit()
    ok = admin_client.post("/api/admin/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert ok.status_code == 200
    cookie = ok.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_csrf_is_enforced(admin_client):
    token = admin_client.headers.pop("X-CSRF-Token")
    assert admin_client.get("/api/admin/dashboard").status_code == 200
    assert admin_client.post("/api/admin/customers", json={"full_name": "Sin CSRF"}).status_code == 403
    admin_client.headers["X-CSRF-Token"] = token
    evil = admin_client.post("/api/admin/customers", json={"full_name": "Origen"}, headers={"Origin": "https://malicioso.example"})
    assert evil.status_code == 403
    assert admin_client.post("/api/admin/customers", json={"full_name": "Con CSRF"}).status_code == 201


def test_request_management_flow(admin_client):
    token = start_chat(admin_client)
    complete_intake(admin_client, token)
    admin_client.post("/api/chat/confirm", headers={"X-Conversation-Token": token})

    listing = admin_client.get("/api/admin/requests?q=porsche").json()
    assert listing["total"] == 1
    request_id = listing["items"][0]["id"]
    detail = admin_client.get(f"/api/admin/requests/{request_id}").json()
    assert detail["conversation"]["messages"] and detail["vehicle"]["model"] == "911 Carrera"

    updated = admin_client.patch(f"/api/admin/requests/{request_id}", json={"status": "presupuesto_pendiente", "quote_amount": "350000"})
    assert updated.status_code == 200 and updated.json()["status"] == "presupuesto_pendiente"
    assert admin_client.patch(f"/api/admin/requests/{request_id}", json={"status": "inventado"}).status_code == 422
    assert admin_client.post(f"/api/admin/requests/{request_id}/notes", json={"body": "Llamar por la tarde"}).status_code == 201
    summary = admin_client.post(f"/api/admin/requests/{request_id}/summary").json()
    assert summary["generated_by"] == "plantilla"

    dashboard = admin_client.get("/api/admin/dashboard").json()["metrics"]
    assert dashboard["requests_total"] == 1 and dashboard["quotes_pending"] == 1 and dashboard["customers_total"] == 1

    search = admin_client.get("/api/admin/customers?q=%25").json()
    assert search["total"] == 0  # Los comodines se escapan.


def test_appointments_prevent_overlap(admin_client):
    customer = admin_client.post("/api/admin/customers", json={"full_name": "Cliente Agenda", "phone": "1155550000"}).json()
    with SessionLocal() as db:
        settings = get_business_settings(db)
        slot = free_slots(db, settings, utcnow().date() + timedelta(days=1), 7, limit=1)[0]
        local = to_local(slot.start, settings.timezone).strftime("%Y-%m-%dT%H:%M")
    first = admin_client.post("/api/admin/appointments", json={"customer_id": customer["id"], "start_local": local})
    assert first.status_code == 201, first.text
    clash = admin_client.post("/api/admin/appointments", json={"customer_id": customer["id"], "start_local": local})
    assert clash.status_code == 409
    night = local[:11] + "23:00"
    assert admin_client.post("/api/admin/appointments", json={"customer_id": customer["id"], "start_local": night}).status_code == 409

    appointment_id = first.json()["id"]
    assert admin_client.patch(f"/api/admin/appointments/{appointment_id}", json={"status": "cancelado"}).json()["status"] == "cancelado"
    assert admin_client.post("/api/admin/appointments", json={"customer_id": customer["id"], "start_local": local}).status_code == 201
    # Reactivar el turno cancelado sobre un horario ocupado no debe permitirse.
    assert admin_client.patch(f"/api/admin/appointments/{appointment_id}", json={"status": "confirmado"}).status_code == 409


def test_radar_drafts_are_never_marked_sent_without_approval(admin_client):
    token = start_chat(admin_client)
    complete_intake(admin_client, token)
    admin_client.post("/api/chat/confirm", headers={"X-Conversation-Token": token})
    incomplete = start_chat(admin_client)
    say(admin_client, incomplete, "Tengo un Maserati Ghibli 2019 con una falla eléctrica. Mi correo es ana@example.com")
    with SessionLocal() as db:
        old = utcnow() - timedelta(days=5)
        for r in db.scalars(select(ServiceRequest)).all():
            r.created_at = old
            r.last_activity_at = old
        for c in db.scalars(select(Conversation)).all():
            c.last_message_at = old
        db.commit()

    radar = admin_client.get("/api/admin/radar").json()["items"]
    kinds = {item["kind"] for item in radar}
    assert {"sin_responder", "incompleta"} <= kinds

    entry = next(i for i in radar if i["kind"] == "sin_responder")
    draft = admin_client.post("/api/admin/radar/drafts", json={"kind": entry["kind"], "request_id": entry["request_id"]}).json()
    assert draft["status"] == "borrador" and draft["generated_by"] == "plantilla" and "Martina" in draft["message"]
    premature = admin_client.patch(f"/api/admin/follow-ups/{draft['id']}", json={"status": "enviado"})
    assert premature.status_code == 409
    assert admin_client.patch(f"/api/admin/follow-ups/{draft['id']}", json={"status": "aprobado"}).json()["status"] == "aprobado"
    sent = admin_client.patch(f"/api/admin/follow-ups/{draft['id']}", json={"status": "enviado", "channel": "whatsapp"}).json()
    assert sent["status"] == "enviado" and sent["sent_at"]

    conv_entry = next(i for i in radar if i["kind"] == "incompleta")
    conv_draft = admin_client.post(
        "/api/admin/radar/drafts", json={"kind": "incompleta", "conversation_id": conv_entry["conversation_id"]}
    )
    assert conv_draft.status_code == 201


def test_security_headers_and_errors(client):
    response = client.get("/api/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    big = client.post("/api/chat/conversations", content=b"x" * 70000, headers={"content-type": "application/json"})
    assert big.status_code == 413
    wrong_type = client.post("/api/chat/conversations", content=b"consent=true", headers={"content-type": "application/x-www-form-urlencoded"})
    assert wrong_type.status_code == 415


def test_rate_limit_on_conversation_start(client):
    codes = [
        client.post("/api/chat/conversations", json={"consent": True, "consent_version": "2026-11"}).status_code
        for _ in range(11)
    ]
    assert codes[-1] == 429


def test_settings_and_services_roundtrip(admin_client):
    settings = admin_client.get("/api/admin/settings").json()
    settings["contact"]["phone"] = "+54 341 456-2870"
    settings["weekly_schedule"]["6"] = [["10:00", "12:00"]]
    settings["closed_dates"] = ["2026-12-25"]
    saved = admin_client.put("/api/admin/settings", json=settings)
    assert saved.status_code == 200, saved.text
    assert saved.json()["weekly_schedule"]["6"] == [["10:00", "12:00"]]
    site = admin_client.get("/api/public/site").json()
    assert site["contact"]["phone"] == "+54 341 456-2870"
    bad = dict(settings, weekly_schedule={**settings["weekly_schedule"], "0": [["18:00", "09:00"]]})
    assert admin_client.put("/api/admin/settings", json=bad).status_code == 422

    service = admin_client.get("/api/admin/services").json()["items"][0]
    patched = admin_client.patch(f"/api/admin/services/{service['id']}", json={"price_info": "Desde ARS 150.000", "is_active": False})
    assert patched.status_code == 200
    public_slugs = {s["slug"] for s in admin_client.get("/api/public/site").json()["services"]}
    assert service["slug"] not in public_slugs
    assert admin_client.get("/api/admin/vehicles?q=porsche").status_code == 200
