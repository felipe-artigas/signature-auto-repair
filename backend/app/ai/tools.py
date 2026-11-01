"""Herramientas que el modelo puede solicitar y su ejecución controlada por el backend.

El modelo nunca accede a la base de datos: solo puede pedir una de estas operaciones con argumentos que se
validan aquí. Las operaciones de registro trabajan exclusivamente con los datos que el cliente confirmó.
"""

import json
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.models import Appointment, Conversation, Customer, Service, ServiceRequest, Vehicle
from app.security import audit
from app.services import intake as intake_svc
from app.services.availability import free_slots, to_local, to_utc
from app.services.business import get_business_settings
from app.services.registry import (
    RegistryError,
    book_appointment,
    create_service_request,
    find_customer,
    get_or_create_customer,
    get_or_create_vehicle,
)
from app.services.summaries import fallback_request_summary

_NULLABLE_STR = {"type": ["string", "null"]}
_NULLABLE_INT = {"type": ["integer", "null"]}


def _fn(name: str, description: str, properties: dict[str, Any] | None = None) -> dict[str, Any]:
    properties = properties or {}
    return {
        "type": "function",
        "name": name,
        "description": description,
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    _fn("get_available_services", "Lista los servicios activos del taller, con su slug y precio configurado si existe."),
    _fn(
        "update_intake",
        "Guarda datos aportados por el cliente en la ficha de la consulta. Enviá null en los campos que no cambian.",
        {
            "full_name": {**_NULLABLE_STR, "description": "Nombre y apellido"},
            "phone": _NULLABLE_STR,
            "email": _NULLABLE_STR,
            "preferred_contact": {"type": ["string", "null"], "enum": ["telefono", "whatsapp", "email", None]},
            "make": {**_NULLABLE_STR, "description": "Marca del vehículo"},
            "model": _NULLABLE_STR,
            "year": _NULLABLE_INT,
            "version": {**_NULLABLE_STR, "description": "Versión o motorización"},
            "mileage_km": _NULLABLE_INT,
            "plate": {**_NULLABLE_STR, "description": "Patente"},
            "vin": _NULLABLE_STR,
            "service_slug": {**_NULLABLE_STR, "description": "Slug obtenido de get_available_services"},
            "problem_description": {**_NULLABLE_STR, "description": "Problema con las palabras del cliente"},
            "symptoms": _NULLABLE_STR,
            "onset": {**_NULLABLE_STR, "description": "Cuándo comenzó el problema"},
            "frequency": {"type": ["string", "null"], "enum": ["constante", "intermitente", "no_sabe", None]},
            "availability": {**_NULLABLE_STR, "description": "Días y franjas en que el cliente puede acercarse"},
            "preferred_date": _NULLABLE_STR,
            "additional_notes": _NULLABLE_STR,
        },
    ),
    _fn(
        "request_confirmation",
        "Muestra al cliente el resumen de los datos recopilados con un botón para confirmarlos.",
    ),
    _fn("find_customer", "Busca si el cliente confirmado ya existe en el sistema. Requiere confirmación previa."),
    _fn("create_customer", "Registra (o reutiliza) al cliente con los datos confirmados."),
    _fn("create_vehicle", "Registra (o reutiliza) el vehículo confirmado del cliente."),
    _fn(
        "create_service_request",
        "Crea la solicitud de atención con los datos confirmados.",
        {"staff_summary": {"type": "string", "description": "Resumen objetivo para el personal, máximo 800 caracteres"}},
    ),
    _fn(
        "check_availability",
        "Consulta horarios realmente libres en la agenda del taller.",
        {
            "date_from": {**_NULLABLE_STR, "description": "Fecha inicial AAAA-MM-DD; null para hoy"},
            "days": {**_NULLABLE_INT, "description": "Cantidad de días a consultar (1 a 14)"},
        },
    ),
    _fn(
        "create_appointment",
        "Solicita un turno en un horario devuelto por check_availability. Queda pendiente de confirmación del taller.",
        {"slot_start": {"type": "string", "description": "Inicio en hora local, formato AAAA-MM-DDTHH:MM"}},
    ),
    _fn(
        "get_customer_requests",
        "Consulta el estado de solicitudes. Sin argumentos devuelve las de esta conversación; para otra solicitud "
        "se requieren el código y el correo electrónico asociado.",
        {"request_code": _NULLABLE_STR, "email": _NULLABLE_STR},
    ),
]

TOOL_NAMES = {t["name"] for t in TOOL_DEFINITIONS}
STATUS_LABELS = {
    "nueva": "Recibida",
    "en_revision": "En revisión",
    "esperando_informacion": "Esperando información",
    "contactado": "Contactado",
    "presupuesto_pendiente": "Propuesta en preparación",
    "aprobado": "Aprobada",
    "rechazado": "No aprobada",
    "finalizado": "Finalizada",
}


class ToolExecutor:
    """Ejecuta herramientas en el contexto de una única conversación."""

    def __init__(self, db: Session, conversation: Conversation):
        self.db = db
        self.conv = conversation
        self.settings = get_settings()
        # Elementos que el frontend debe mostrar (por ejemplo, la tarjeta de confirmación).
        self.ui_events: list[dict[str, Any]] = []

    def execute(self, name: str, raw_arguments: str) -> dict[str, Any]:
        if name not in TOOL_NAMES:
            return {"ok": False, "error": "Herramienta desconocida."}
        if self.conv.tool_call_count >= self.settings.chat_max_tool_calls_per_conversation:
            return {"ok": False, "error": "Se alcanzó el límite de acciones de esta conversación."}
        self.conv.tool_call_count += 1
        try:
            args = json.loads(raw_arguments or "{}")
            if not isinstance(args, dict):
                raise ValueError
        except ValueError:
            return {"ok": False, "error": "Argumentos inválidos."}
        try:
            result = getattr(self, f"_tool_{name}")(args)
        except RegistryError as exc:
            self.db.rollback()
            result = {"ok": False, "error": str(exc)}
        audit(
            self.db,
            "asistente",
            f"tool:{name}",
            entity="conversation",
            entity_id=self.conv.id,
            details={"ok": result.get("ok", False)},
        )
        self.db.commit()
        return result

    # --- Herramientas -----------------------------------------------------------------------------

    def _tool_get_available_services(self, _: dict) -> dict:
        services = self.db.scalars(
            select(Service).where(Service.is_active.is_(True)).order_by(Service.sort_order, Service.name)
        ).all()
        return {
            "ok": True,
            "services": [
                {
                    "slug": s.slug,
                    "name": s.name,
                    "category": s.category,
                    "description": s.description,
                    "price_info": s.price_info or "A cotizar luego de la evaluación del vehículo",
                }
                for s in services
            ],
        }

    def _tool_update_intake(self, args: dict) -> dict:
        if self.conv.status == "registrada":
            return {
                "ok": False,
                "error": "La solicitud ya fue registrada. Los nuevos comentarios quedan en la conversación, "
                "que el taller puede leer.",
            }
        clean, errors = intake_svc.validate_update(self.db, args)
        if clean:
            merged = dict(self.conv.intake or {})
            merged.update(clean)
            self.conv.intake = merged
            if self.conv.pending_summary is not None:
                # Cualquier cambio invalida el resumen presentado: debe volver a confirmarse.
                self.conv.pending_summary = None
                self.conv.status = "activa"
        intake = self.conv.intake or {}
        return {
            "ok": not errors,
            "saved_fields": sorted(clean),
            "errors": errors,
            "missing_required": intake_svc.missing_fields(intake),
            "missing_recommended": intake_svc.missing_recommended(intake),
        }

    def _tool_request_confirmation(self, _: dict) -> dict:
        if self.conv.status == "registrada":
            return {"ok": False, "error": "La solicitud ya fue registrada."}
        intake = {k: v for k, v in (self.conv.intake or {}).items() if not k.startswith("_")}
        missing = intake_svc.missing_fields(intake)
        if missing:
            return {"ok": False, "error": "Faltan datos obligatorios.", "missing_required": missing}
        self.conv.pending_summary = intake
        self.conv.status = "esperando_confirmacion"
        lines = intake_svc.summary_lines(self.db, intake)
        self.ui_events.append({"type": "confirmation", "lines": lines})
        return {"ok": True, "shown_to_customer": True, "next": "Esperar a que el cliente presione Confirmar."}

    def _confirmed(self) -> dict | None:
        return self.conv.confirmed_snapshot if self.conv.confirmed_at else None

    def _tool_find_customer(self, _: dict) -> dict:
        data = self._confirmed()
        if data is None:
            return {"ok": False, "error": "El cliente todavía no confirmó sus datos."}
        # Solo se informa si existe: nunca se devuelven datos de clientes al modelo.
        return {"ok": True, "existing_customer": find_customer(self.db, data.get("email"), data.get("phone")) is not None}

    def _tool_create_customer(self, _: dict) -> dict:
        data = self._confirmed()
        if data is None:
            return {"ok": False, "error": "El cliente todavía no confirmó sus datos."}
        if self.conv.customer_id:
            return {"ok": True, "already_linked": True}
        customer, created, differences = get_or_create_customer(
            self.db,
            data,
            source="asistente",
            consent_at=self.conv.consent_at,
            consent_version=self.conv.consent_version,
        )
        self.conv.customer_id = customer.id
        if differences:
            self.conv.intake = {**(self.conv.intake or {}), "_contact_differences": differences}
        return {"ok": True, "created": created}

    def _tool_create_vehicle(self, _: dict) -> dict:
        data = self._confirmed()
        if data is None or not self.conv.customer_id:
            return {"ok": False, "error": "Primero debe registrarse el cliente con create_customer."}
        if self.conv.vehicle_id:
            return {"ok": True, "already_linked": True}
        customer = self.db.get(Customer, self.conv.customer_id)
        vehicle, created, notes = get_or_create_vehicle(self.db, customer, data)
        self.conv.vehicle_id = vehicle.id
        if notes:
            self.conv.intake = {**(self.conv.intake or {}), "_vehicle_notes": notes}
        return {"ok": True, "created": created}

    def _tool_create_service_request(self, args: dict) -> dict:
        data = self._confirmed()
        if data is None or not self.conv.customer_id or not self.conv.vehicle_id:
            return {"ok": False, "error": "Deben registrarse antes el cliente y el vehículo."}
        existing = self.db.scalar(select(ServiceRequest).where(ServiceRequest.conversation_id == self.conv.id))
        if existing:
            return {"ok": True, "already_created": True, "request_code": existing.code}
        customer = self.db.get(Customer, self.conv.customer_id)
        vehicle = self.db.get(Vehicle, self.conv.vehicle_id)
        summary = intake_svc.clean_text(args.get("staff_summary"), 800)
        extra = {}
        intake = self.conv.intake or {}
        if intake.get("_contact_differences"):
            extra["contacto_declarado_distinto"] = intake["_contact_differences"]
        if intake.get("_vehicle_notes"):
            extra.update(intake["_vehicle_notes"])
        request = create_service_request(
            self.db,
            customer=customer,
            vehicle=vehicle,
            data=data,
            source="asistente",
            conversation_id=self.conv.id,
            ai_summary=summary or fallback_request_summary(data),
            extra=extra,
        )
        self.conv.status = "registrada"
        audit(self.db, "asistente", "request_created", entity="service_request", entity_id=request.id)
        return {"ok": True, "request_code": request.code, "status": STATUS_LABELS[request.status]}

    def _tool_check_availability(self, args: dict) -> dict:
        settings = get_business_settings(self.db)
        start_day = to_local(utcnow(), settings.timezone).date()
        if args.get("date_from"):
            try:
                start_day = max(start_day, date.fromisoformat(str(args["date_from"])[:10]))
            except ValueError:
                return {"ok": False, "error": "La fecha debe tener formato AAAA-MM-DD."}
        days = args.get("days") or 7
        days = max(1, min(int(days), 14))
        slots = free_slots(self.db, settings, start_day, days, limit=8)
        return {
            "ok": True,
            "timezone": settings.timezone,
            "slots": [to_local(s.start, settings.timezone).strftime("%Y-%m-%dT%H:%M") for s in slots],
            "note": "Horarios libres al momento de la consulta. El turno queda solicitado hasta que el taller lo confirme.",
        }

    def _tool_create_appointment(self, args: dict) -> dict:
        request = self.db.scalar(select(ServiceRequest).where(ServiceRequest.conversation_id == self.conv.id))
        if request is None:
            return {"ok": False, "error": "Primero debe registrarse la solicitud de atención."}
        active = self.db.scalar(
            select(Appointment).where(
                Appointment.service_request_id == request.id,
                Appointment.status.in_(("solicitado", "confirmado")),
            )
        )
        settings = get_business_settings(self.db)
        if active:
            return {
                "ok": False,
                "error": "Esta solicitud ya tiene un turno solicitado.",
                "existing_slot": to_local(active.start_at, settings.timezone).strftime("%Y-%m-%dT%H:%M"),
            }
        try:
            local = datetime.strptime(str(args.get("slot_start", ""))[:16], "%Y-%m-%dT%H:%M")
        except ValueError:
            return {"ok": False, "error": "Formato de horario inválido."}
        start = to_utc(local, settings.timezone)
        if start < utcnow() + timedelta(hours=settings.min_notice_hours):
            return {"ok": False, "error": "El horario no respeta la anticipación mínima del taller."}
        appointment = book_appointment(
            self.db,
            customer_id=request.customer_id,
            vehicle_id=request.vehicle_id,
            service_request_id=request.id,
            start=start,
            created_by="asistente",
        )
        request.last_activity_at = utcnow()
        audit(self.db, "asistente", "appointment_requested", entity="appointment", entity_id=appointment.id)
        return {
            "ok": True,
            "status": "solicitado",
            "slot": local.strftime("%Y-%m-%dT%H:%M"),
            "note": "El turno queda solicitado. El taller lo confirmará por el medio de contacto indicado.",
        }

    def _tool_get_customer_requests(self, args: dict) -> dict:
        code = (args.get("request_code") or "").strip().upper()
        email = intake_svc.normalize_email(args.get("email") or "") if args.get("email") else None
        if not code:
            requests = self.db.scalars(
                select(ServiceRequest).where(ServiceRequest.conversation_id == self.conv.id)
            ).all()
        else:
            self.conv.lookup_attempts += 1
            if self.conv.lookup_attempts > 5:
                return {"ok": False, "error": "Se superó el límite de consultas de esta conversación."}
            request = self.db.scalar(select(ServiceRequest).where(ServiceRequest.code == code))
            # Se exige que código y correo coincidan; el mensaje de error no revela cuál falló.
            if request is None or not email or request.customer.email != email:
                return {"ok": False, "error": "No se encontró una solicitud con esos datos."}
            requests = [request]
        return {
            "ok": True,
            "requests": [
                {
                    "code": r.code,
                    "status": STATUS_LABELS[r.status],
                    "service": r.requested_service,
                    "created": r.created_at.strftime("%Y-%m-%d"),
                }
                for r in requests
            ],
        }
