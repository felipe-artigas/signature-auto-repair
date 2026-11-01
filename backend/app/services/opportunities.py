"""Radar de oportunidades comerciales: detección por reglas sobre datos reales."""

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.deps import iso
from app.models import (
    REQUEST_OPEN_STATUSES,
    Appointment,
    Conversation,
    FollowUp,
    ServiceRequest,
)
from app.services.business import get_business_settings
from app.services.summaries import vehicle_label

KIND_LABELS = {
    "sin_responder": "Consulta sin responder",
    "incompleta": "Solicitud no completada",
    "presupuesto_pendiente": "Presupuesto pendiente",
    "turno_sin_confirmar": "Turno sin confirmar",
    "aprobado_sin_turno": "Aprobado sin turno",
    "sin_actualizacion": "Sin actualización",
}
PRIORITY = {
    "sin_responder": 1,
    "turno_sin_confirmar": 2,
    "presupuesto_pendiente": 2,
    "aprobado_sin_turno": 2,
    "incompleta": 3,
    "sin_actualizacion": 3,
}


def _days(delta: timedelta) -> float:
    return round(delta.total_seconds() / 86400, 1)


def _request_entry(kind: str, request: ServiceRequest, reference, detail: str) -> dict[str, Any]:
    customer = request.customer
    vehicle = request.vehicle
    return {
        "key": f"{kind}:request:{request.id}",
        "kind": kind,
        "label": KIND_LABELS[kind],
        "priority": PRIORITY[kind],
        "request_id": request.id,
        "request_code": request.code,
        "conversation_id": None,
        "customer_id": customer.id,
        "customer_name": customer.full_name,
        "phone": customer.phone,
        "email": customer.email,
        "preferred_contact": customer.preferred_contact,
        "vehicle": f"{vehicle.make} {vehicle.model} {vehicle.year or ''}".strip() if vehicle else None,
        "status": request.status,
        "since": iso(reference),
        "age_days": _days(utcnow() - reference),
        "detail": detail,
    }


def detect(db: Session) -> list[dict[str, Any]]:
    settings = get_business_settings(db)
    now = utcnow()
    stale = now - timedelta(days=settings.stale_after_days)
    results: list[dict[str, Any]] = []
    seen_requests: set[int] = set()

    open_requests = db.scalars(
        select(ServiceRequest).where(ServiceRequest.status.in_(REQUEST_OPEN_STATUSES))
    ).all()
    for r in open_requests:
        if r.status == "nueva" and r.created_at < now - timedelta(hours=4):
            results.append(_request_entry("sin_responder", r, r.created_at, "Solicitud nueva sin gestión del taller."))
            seen_requests.add(r.id)
        elif r.status == "presupuesto_pendiente" and r.last_activity_at < now - timedelta(days=2):
            results.append(
                _request_entry(
                    "presupuesto_pendiente", r, r.quote_sent_at or r.last_activity_at,
                    "Propuesta enviada o en preparación sin respuesta del cliente.",
                )
            )
            seen_requests.add(r.id)
        elif r.last_activity_at < stale:
            results.append(
                _request_entry("sin_actualizacion", r, r.last_activity_at, "Solicitud abierta sin movimientos recientes.")
            )
            seen_requests.add(r.id)

    approved = db.scalars(select(ServiceRequest).where(ServiceRequest.status == "aprobado")).all()
    for r in approved:
        has_appointment = any(a.status in ("solicitado", "confirmado") for a in r.appointments)
        if not has_appointment and r.id not in seen_requests:
            results.append(
                _request_entry("aprobado_sin_turno", r, r.last_activity_at, "Propuesta aprobada sin turno coordinado.")
            )

    pending_appointments = db.scalars(
        select(Appointment).where(Appointment.status == "solicitado", Appointment.created_at < now - timedelta(hours=24))
    ).all()
    for a in pending_appointments:
        entry = {
            "key": f"turno_sin_confirmar:appointment:{a.id}",
            "kind": "turno_sin_confirmar",
            "label": KIND_LABELS["turno_sin_confirmar"],
            "priority": PRIORITY["turno_sin_confirmar"],
            "request_id": a.service_request_id,
            "request_code": a.service_request.code if a.service_request else None,
            "conversation_id": None,
            "customer_id": a.customer_id,
            "customer_name": a.customer.full_name,
            "phone": a.customer.phone,
            "email": a.customer.email,
            "preferred_contact": a.customer.preferred_contact,
            "vehicle": f"{a.vehicle.make} {a.vehicle.model}" if a.vehicle else None,
            "status": a.status,
            "since": iso(a.created_at),
            "age_days": _days(now - a.created_at),
            "detail": "Turno solicitado que todavía no fue confirmado con el cliente.",
            "appointment_start": iso(a.start_at),
        }
        results.append(entry)

    incomplete = db.scalars(
        select(Conversation).where(
            Conversation.status.in_(("activa", "esperando_confirmacion")),
            Conversation.customer_id.is_(None),
            Conversation.last_message_at < now - timedelta(hours=2),
        )
    ).all()
    for c in incomplete:
        intake = c.intake or {}
        if not (intake.get("phone") or intake.get("email")):
            continue  # Sin datos de contacto no hay seguimiento posible.
        results.append(
            {
                "key": f"incompleta:conversation:{c.id}",
                "kind": "incompleta",
                "label": KIND_LABELS["incompleta"],
                "priority": PRIORITY["incompleta"],
                "request_id": None,
                "request_code": None,
                "conversation_id": c.id,
                "customer_id": None,
                "customer_name": intake.get("full_name") or "Visitante sin nombre",
                "phone": intake.get("phone"),
                "email": intake.get("email"),
                "preferred_contact": intake.get("preferred_contact"),
                "vehicle": vehicle_label(intake) or None,
                "status": c.status,
                "since": iso(c.last_message_at),
                "age_days": _days(now - c.last_message_at),
                "detail": "Inició una consulta con el asistente y no llegó a confirmarla.",
            }
        )

    # Se adjunta el último seguimiento registrado para cada oportunidad.
    for entry in results:
        query = select(FollowUp).order_by(FollowUp.id.desc())
        if entry["request_id"]:
            query = query.where(FollowUp.service_request_id == entry["request_id"])
        elif entry["conversation_id"]:
            query = query.where(FollowUp.conversation_id == entry["conversation_id"])
        else:
            query = query.where(FollowUp.customer_id == entry["customer_id"])
        last = db.scalar(query.limit(1))
        entry["last_follow_up"] = (
            {"id": last.id, "status": last.status, "created_at": iso(last.created_at), "sent_at": iso(last.sent_at)}
            if last
            else None
        )
    results.sort(key=lambda e: (e["priority"], -e["age_days"]))
    return results
