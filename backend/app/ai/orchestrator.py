import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.prompts import ASSISTANT_INSTRUCTIONS
from app.ai.providers import Provider, ProviderError, ProviderResult, TurnContext, get_provider
from app.ai.tools import TOOL_DEFINITIONS, ToolExecutor
from app.config import get_settings
from app.db import utcnow
from app.models import AIUsage, Conversation, Message, ServiceRequest
from app.services import intake as intake_svc
from app.services.availability import to_local
from app.services.business import get_business_settings

HISTORY_LIMIT = 30
FALLBACK_REPLY = (
    "Disculpe, no pude procesar su mensaje en este momento. Puede intentarlo nuevamente o comunicarse con el "
    "taller por los canales de contacto."
)
_EMOJI = re.compile(
    "[\U0001f000-\U0001faff\U00002600-\U000027bf\U0001f900-\U0001f9ff\U00002b00-\U00002bff️‍]"
)


class BudgetExceeded(RuntimeError):
    pass


def clean_reply(text: str) -> str:
    text = _EMOJI.sub("", text or "")
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)  # La interfaz muestra texto plano.
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _usage_today(db: Session) -> AIUsage:
    today = utcnow().date()
    usage = db.get(AIUsage, today)
    if usage is None:
        usage = AIUsage(day=today, requests=0, input_tokens=0, output_tokens=0)
        db.add(usage)
        db.flush()
    return usage


def check_budget(db: Session, provider: Provider) -> AIUsage:
    settings = get_settings()
    usage = _usage_today(db)
    if provider.name == "openai" and (
        usage.requests >= settings.ai_daily_request_budget
        or usage.input_tokens + usage.output_tokens >= settings.ai_daily_token_budget
    ):
        raise BudgetExceeded("Se alcanzó el límite diario de uso del asistente.")
    return usage


def record_usage(db: Session, usage: AIUsage, result: ProviderResult | None = None, tokens: tuple[int, int] = (0, 0)):
    usage.requests += 1
    usage.input_tokens += result.input_tokens if result else tokens[0]
    usage.output_tokens += result.output_tokens if result else tokens[1]


def _offered_slots(conv: Conversation) -> list[str]:
    for message in reversed(conv.messages):
        if message.role == "tool" and message.tool_name == "check_availability" and message.payload:
            return list(message.payload.get("slots", []))[:6]
    return []


def _state_message(db: Session, conv: Conversation, ctx: TurnContext) -> dict[str, Any]:
    settings = get_business_settings(db)
    now_local = to_local(utcnow(), settings.timezone)
    visible = {k: v for k, v in ctx.intake.items() if not k.startswith("_")}
    state = {
        "fecha_hora_local": now_local.strftime("%A %Y-%m-%d %H:%M"),
        "zona_horaria": settings.timezone,
        "estado_conversacion": ctx.status,
        "datos_recopilados": visible,
        "faltan_obligatorios": intake_svc.missing_fields(visible),
        "faltan_recomendados": intake_svc.missing_recommended(visible),
        "codigo_solicitud": ctx.request_code,
        "horarios_ofrecidos": ctx.offered_slots,
    }
    return {
        "role": "developer",
        "content": "Estado actual de la consulta (generado por el sistema, no por el cliente):\n"
        + json.dumps(state, ensure_ascii=False),
    }


def _history_items(conv: Conversation) -> list[dict[str, Any]]:
    items = []
    relevant = [m for m in conv.messages if m.role in ("user", "assistant", "event")][-HISTORY_LIMIT:]
    for message in relevant:
        if message.role == "event":
            items.append({"role": "developer", "content": f"EVENTO: {message.content}"})
        elif message.content:
            items.append({"role": message.role, "content": message.content})
    return items


def run_turn(
    db: Session, conv: Conversation, *, user_text: str | None = None, event: str | None = None,
    provider: Provider | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    provider = provider or get_provider()
    usage = check_budget(db, provider)

    now = utcnow()
    if user_text is not None:
        db.add(Message(conversation_id=conv.id, role="user", content=user_text, created_at=now))
    if event is not None:
        db.add(Message(conversation_id=conv.id, role="event", content=event, created_at=now))
    conv.message_count += 1
    conv.last_message_at = now
    db.commit()
    db.refresh(conv)

    request = db.scalar(select(ServiceRequest).where(ServiceRequest.conversation_id == conv.id))
    ctx = TurnContext(
        intake=dict(conv.intake or {}),
        status=conv.status,
        offered_slots=_offered_slots(conv),
        request_code=request.code if request else None,
    )
    items = [_state_message(db, conv, ctx), *_history_items(conv)]
    executor = ToolExecutor(db, conv)
    reply = ""

    try:
        for _ in range(settings.ai_max_tool_rounds):
            result = provider.respond(ASSISTANT_INSTRUCTIONS, items, TOOL_DEFINITIONS, ctx)
            record_usage(db, usage, result)
            conv.input_tokens += result.input_tokens
            conv.output_tokens += result.output_tokens
            items.extend(result.output_items)
            if not result.function_calls:
                reply = result.text
                break
            for call in result.function_calls:
                output = executor.execute(call.name, call.arguments)
                items.append({"type": "function_call_output", "call_id": call.call_id, "output": json.dumps(output, ensure_ascii=False)})
                db.add(Message(conversation_id=conv.id, role="tool", tool_name=call.name, payload=output))
            db.commit()
            db.refresh(conv)
            ctx.intake = dict(conv.intake or {})
            ctx.status = conv.status
            ctx.offered_slots = _offered_slots(conv) or ctx.offered_slots
    except ProviderError:
        reply = FALLBACK_REPLY
        db.rollback()

    reply = clean_reply(reply) or FALLBACK_REPLY
    payload = {"ui_events": executor.ui_events} if executor.ui_events else None
    db.add(Message(conversation_id=conv.id, role="assistant", content=reply, payload=payload, created_at=utcnow()))
    conv.last_message_at = utcnow()
    db.commit()
    return {"reply": reply, "ui_events": executor.ui_events, "status": conv.status}
