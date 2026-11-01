from datetime import timedelta

from sqlalchemy import func, select

from app.ai.tools import ToolExecutor
from app.db import SessionLocal, utcnow
from app.models import Appointment, Conversation, Customer, ServiceRequest, Vehicle
from tests.conftest import say, start_chat


def complete_intake(client, token):
    say(client, token, "Hola, tengo un Porsche 911 Carrera 2020. Siento una vibración cuando acelero.")
    say(client, token, "45.000 km")
    say(client, token, "Hace dos semanas")
    say(client, token, "Es intermitente")
    say(client, token, "Me llamo Martina Rossi")
    say(client, token, "+54 9 11 5555-1234")
    say(client, token, "martina.rossi@example.com")
    say(client, token, "Por WhatsApp")
    return say(client, token, "Martes o jueves por la mañana")


def test_consent_required(client):
    response = client.post("/api/chat/conversations", json={"consent": False, "consent_version": "2026-11"})
    assert response.status_code == 400


def test_full_flow_registers_request_and_appointment(client):
    token = start_chat(client)
    first = say(client, token, "Hola, tengo un Porsche 911 Carrera 2020. Siento una vibración cuando acelero.")
    assert first["mode"] == "mock"
    assert "kilómetros" in first["reply"]

    final = complete_intake(client, token)
    assert final["ui_events"] and final["ui_events"][0]["type"] == "confirmation"
    labels = {line["field"]: line["value"] for line in final["ui_events"][0]["lines"]}
    assert labels["make"] == "Porsche" and labels["model"] == "911 Carrera" and labels["year"] == "2020"
    assert labels["mileage_km"] == "45.000 km"

    # Nada se registra antes de la confirmación.
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Customer.id))) == 0

    confirmed = client.post("/api/chat/confirm", headers={"X-Conversation-Token": token})
    assert confirmed.status_code == 200, confirmed.text
    assert "SAR-" in confirmed.json()["reply"]

    with SessionLocal() as db:
        request = db.scalar(select(ServiceRequest))
        assert request.customer.email == "martina.rossi@example.com"
        assert request.vehicle.make == "Porsche" and request.vehicle.mileage_km == 45000
        assert request.frequency == "intermitente" and request.status == "nueva"
        assert "Sin diagnóstico" in request.ai_summary

    # Confirmar dos veces no duplica registros.
    again = client.post("/api/chat/confirm", headers={"X-Conversation-Token": token})
    assert again.status_code == 409

    slots = say(client, token, "Sí, quiero un turno")
    assert "horarios disponibles" in slots["reply"]
    booked = say(client, token, "1")
    assert "pendiente de confirmación" in booked["reply"]
    with SessionLocal() as db:
        appointment = db.scalar(select(Appointment))
        assert appointment.status == "solicitado" and appointment.created_by == "asistente"
        assert db.scalar(select(func.count(Customer.id))) == 1
        assert db.scalar(select(func.count(Vehicle.id))) == 1


def test_returning_customer_is_not_duplicated_or_overwritten(client):
    for name in ("Martina Rossi", "Otra Persona"):
        token = start_chat(client)
        say(client, token, "Tengo un BMW 330i 2021 y hace un ruido cuando paso por calles irregulares")
        say(client, token, "45000 km")
        say(client, token, "hace un mes")
        say(client, token, "constante")
        say(client, token, f"Me llamo {name}")
        say(client, token, "1155551234")
        say(client, token, "martina.rossi@example.com")
        say(client, token, "por mail")
        say(client, token, "lunes")
        assert client.post("/api/chat/confirm", headers={"X-Conversation-Token": token}).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Customer.id))) == 1
        assert db.scalar(select(func.count(Vehicle.id))) == 1
        customer = db.scalar(select(Customer))
        assert customer.full_name == "Martina Rossi"
        second = db.scalars(select(ServiceRequest).order_by(ServiceRequest.id)).all()[-1]
        assert second.extra_data["contacto_declarado_distinto"]["full_name"] == "Otra Persona"


def test_conversations_are_isolated(client):
    token_a = start_chat(client)
    say(client, token_a, "Tengo un Audi RS6 2022 con una luz de testigo encendida")
    token_b = start_chat(client)
    data_b = client.get("/api/chat/conversation", headers={"X-Conversation-Token": token_b}).json()
    assert all("Audi" not in m["content"] for m in data_b["messages"])
    assert client.get("/api/chat/conversation", headers={"X-Conversation-Token": "inventado"}).status_code == 404
    assert client.get("/api/chat/conversation").status_code == 401


def test_message_limits(client):
    token = start_chat(client)
    long = client.post("/api/chat/messages", json={"message": "a" * 1001}, headers={"X-Conversation-Token": token})
    assert long.status_code == 422


def test_registration_tools_require_confirmation(client):
    token = start_chat(client)
    say(client, token, "Tengo un Ferrari Roma 2023 con ruido en frenos")
    with SessionLocal() as db:
        conv = db.scalar(select(Conversation))
        executor = ToolExecutor(db, conv)
        for tool in ("find_customer", "create_customer", "create_vehicle"):
            assert executor.execute(tool, "{}")["ok"] is False
        assert executor.execute("create_service_request", '{"staff_summary": "x"}')["ok"] is False
        assert executor.execute("create_appointment", '{"slot_start": "2030-01-01T10:00"}')["ok"] is False
        assert executor.execute("drop_tables", "{}")["ok"] is False
        assert executor.execute("update_intake", "no-es-json")["ok"] is False
        result = executor.execute("update_intake", '{"email": "no-es-un-correo", "year": 1800, "vin": "123"}')
        assert set(result["errors"]) == {"email", "year", "vin"}
        assert db.scalar(select(func.count(Customer.id))) == 0


def test_request_lookup_requires_code_and_email(client):
    token = start_chat(client)
    complete_intake(client, token)
    client.post("/api/chat/confirm", headers={"X-Conversation-Token": token})
    with SessionLocal() as db:
        code = db.scalar(select(ServiceRequest.code))
    other = start_chat(client)
    say(client, other, "hola")
    with SessionLocal() as db:
        conv = db.scalars(select(Conversation).order_by(Conversation.id)).all()[-1]
        executor = ToolExecutor(db, conv)
        denied = executor.execute("get_customer_requests", f'{{"request_code": "{code}", "email": "otro@example.com"}}')
        assert denied["ok"] is False and "requests" not in denied
        allowed = executor.execute(
            "get_customer_requests", f'{{"request_code": "{code}", "email": "martina.rossi@example.com"}}'
        )
        assert allowed["ok"] and allowed["requests"][0]["code"] == code
        assert set(allowed["requests"][0]) == {"code", "status", "service", "created"}


def test_assistant_cannot_book_taken_slot(client):
    token = start_chat(client)
    complete_intake(client, token)
    client.post("/api/chat/confirm", headers={"X-Conversation-Token": token})
    with SessionLocal() as db:
        conv = db.scalar(select(Conversation))
        executor = ToolExecutor(db, conv)
        slots = executor.execute("check_availability", '{"date_from": null, "days": 7}')["slots"]
        assert slots
        request = db.scalar(select(ServiceRequest))
        from app.services.availability import to_utc
        from app.services.business import get_business_settings
        from datetime import datetime

        tz = get_business_settings(db).timezone
        start = to_utc(datetime.strptime(slots[0], "%Y-%m-%dT%H:%M"), tz)
        db.add(Appointment(customer_id=request.customer_id, start_at=start, end_at=start + timedelta(hours=1),
                           status="confirmado", created_by="panel"))
        db.commit()
        taken = executor.execute("create_appointment", f'{{"slot_start": "{slots[0]}"}}')
        assert taken["ok"] is False
        past = executor.execute("create_appointment", f'{{"slot_start": "{(utcnow() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")}"}}')
        assert past["ok"] is False
