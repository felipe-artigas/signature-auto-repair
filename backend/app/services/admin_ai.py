"""Textos internos para el panel: resúmenes de solicitudes y borradores de seguimiento.

Con IA habilitada se usa OpenAI con salida estructurada. En modo de pruebas se usan plantillas,
y el resultado se identifica como tal (generated_by = "plantilla").
"""

import json
from typing import Any

from sqlalchemy.orm import Session

from app.ai.orchestrator import check_budget, clean_reply, record_usage
from app.ai.prompts import ADMIN_ASSIST_INSTRUCTIONS
from app.ai.providers import get_provider
from app.models import ServiceRequest
from app.services.summaries import fallback_request_summary

FOLLOWUP_SCHEMA = {
    "type": "object",
    "properties": {
        "suggestion": {"type": "string", "description": "Sugerencia interna breve para el personal"},
        "message": {"type": "string", "description": "Mensaje para el cliente, máximo 90 palabras"},
    },
    "required": ["suggestion", "message"],
    "additionalProperties": False,
}

TEMPLATES = {
    "sin_responder": (
        "Contactar hoy: la solicitud todavía no tuvo respuesta del taller.",
        "Estimado/a {name}, le escribimos de Signature Auto Repair en relación con su consulta{about}. "
        "Queremos coordinar la evaluación de su vehículo. ¿Le resulta conveniente que lo contactemos para acordar "
        "un horario?",
    ),
    "incompleta": (
        "El visitante inició una consulta y no la confirmó. Ofrecer completarla con ayuda del equipo.",
        "Estimado/a {name}, notamos que comenzó una consulta en Signature Auto Repair{about} y no llegó a "
        "completarla. Si lo desea, podemos ayudarlo a finalizarla y coordinar la atención de su vehículo.",
    ),
    "presupuesto_pendiente": (
        "Consultar si el cliente revisó la propuesta y si tiene dudas.",
        "Estimado/a {name}, queríamos saber si pudo revisar la propuesta de servicio{about}. Quedamos a su "
        "disposición para responder cualquier consulta.",
    ),
    "turno_sin_confirmar": (
        "Confirmar el turno solicitado o proponer otro horario.",
        "Estimado/a {name}, recibimos su solicitud de turno{about}. Le escribimos para confirmar el horario o, si "
        "lo prefiere, proponerle una alternativa.",
    ),
    "aprobado_sin_turno": (
        "Coordinar fecha de ingreso del vehículo.",
        "Estimado/a {name}, gracias por aprobar la propuesta{about}. ¿Qué día le resulta conveniente para acercar "
        "el vehículo al taller?",
    ),
    "sin_actualizacion": (
        "Revisar el estado y dar una actualización al cliente.",
        "Estimado/a {name}, le escribimos para darle seguimiento a su consulta{about}. ¿Hay algo en lo que podamos "
        "ayudarlo?",
    ),
}


def _usage_and_provider(db: Session):
    provider = get_provider()
    if provider.name != "openai":
        return None, None
    return provider, check_budget(db, provider)


def generate_follow_up(db: Session, kind: str, context: dict[str, Any]) -> tuple[str, str, str]:
    """Devuelve (sugerencia, mensaje, generado_por)."""
    provider, usage = _usage_and_provider(db)
    if provider is not None:
        prompt = (
            "Generá una sugerencia interna y un mensaje de seguimiento para un cliente del taller. Tipo de "
            f"oportunidad: {kind}. Datos reales (no agregues otros):\n"
            + json.dumps(context, ensure_ascii=False, default=str)
        )
        text, tin, tout = provider.complete(ADMIN_ASSIST_INSTRUCTIONS, prompt, 600, schema=FOLLOWUP_SCHEMA)
        record_usage(db, usage, tokens=(tin, tout))
        data = json.loads(text)
        return clean_reply(data["suggestion"]), clean_reply(data["message"]), "ia"

    suggestion, template = TEMPLATES[kind]
    first_name = (context.get("customer_name") or "").split(" ")[0] or "cliente"
    about = f" sobre su {context['vehicle']}" if context.get("vehicle") else ""
    return suggestion, template.format(name=first_name, about=about), "plantilla"


def generate_request_summary(db: Session, request: ServiceRequest) -> tuple[str, str]:
    data = {
        "make": request.vehicle.make if request.vehicle else None,
        "model": request.vehicle.model if request.vehicle else None,
        "version": request.vehicle.version if request.vehicle else None,
        "year": request.vehicle.year if request.vehicle else None,
        "mileage_km": request.vehicle.mileage_km if request.vehicle else None,
        "problem_description": request.problem_description,
        "symptoms": request.symptoms,
        "onset": request.onset,
        "frequency": request.frequency,
        "availability": request.customer_availability,
        "preferred_date": request.preferred_date,
    }
    provider, usage = _usage_and_provider(db)
    if provider is None:
        return fallback_request_summary(data), "plantilla"
    transcript = []
    if request.conversation:
        transcript = [
            f"{'Cliente' if m.role == 'user' else 'Asistente'}: {m.content}"
            for m in request.conversation.messages
            if m.role in ("user", "assistant")
        ][-30:]
    prompt = (
        "Redactá un resumen objetivo para el personal del taller (máximo 120 palabras). Separá: vehículo, "
        "motivo declarado, síntomas y contexto declarados por el cliente, disponibilidad y datos faltantes. "
        "No incluyas diagnósticos ni precios. Datos:\n"
        + json.dumps({k: v for k, v in data.items() if v}, ensure_ascii=False)
        + "\nConversación:\n"
        + "\n".join(transcript)
    )
    text, tin, tout = provider.complete(ADMIN_ASSIST_INSTRUCTIONS, prompt, 500)
    record_usage(db, usage, tokens=(tin, tout))
    return clean_reply(text) or fallback_request_summary(data), "ia"
