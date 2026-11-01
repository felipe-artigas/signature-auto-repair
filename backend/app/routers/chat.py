"""API del asistente público.

Cada visitante accede solo a su conversación mediante un token aleatorio enviado en la cabecera
X-Conversation-Token. En la base se guarda únicamente el hash del token.
"""

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.orchestrator import BudgetExceeded, run_turn
from app.config import get_settings
from app.db import get_db, utcnow
from app.models import Conversation
from app.ratelimit import client_ip, enforce
from app.security import keyed_hash, new_token
from app.services.intake import summary_lines

router = APIRouter(prefix="/api/chat", tags=["asistente"])

CONSENT_VERSION = "2026-11"
GREETING = (
    "Bienvenido a Signature Auto Repair. Soy el asistente de recepción del taller. Cuénteme qué necesita: "
    "el vehículo, el servicio que busca o lo que está notando, y lo ayudo a registrar su solicitud."
)


class StartIn(BaseModel):
    consent: bool
    consent_version: str = Field(max_length=20)


class MessageIn(BaseModel):
    message: str = Field(min_length=1)


def _conversation(db: Session, token: str | None) -> Conversation:
    if not token or len(token) > 100:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Conversación no válida.")
    conv = db.scalar(select(Conversation).where(Conversation.token_hash == keyed_hash(token)))
    if conv is None or conv.status == "cerrada":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La conversación no existe o fue cerrada.")
    return conv


def _public_messages(conv: Conversation) -> list[dict]:
    result = []
    for m in conv.messages:
        if m.role in ("user", "assistant"):
            result.append(
                {"role": m.role, "content": m.content, "ui_events": (m.payload or {}).get("ui_events", [])}
            )
    return result


@router.post("/conversations", status_code=201)
def start(body: StartIn, request: Request, db: Session = Depends(get_db)):
    enforce(request, "chat-start", limit=10, window_seconds=3600)
    if not body.consent or body.consent_version != CONSENT_VERSION:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Es necesario aceptar la política de privacidad vigente.")
    token = new_token()
    now = utcnow()
    conv = Conversation(
        token_hash=keyed_hash(token),
        consent_at=now,
        consent_version=CONSENT_VERSION,
        ai_mode="openai" if get_settings().ai_enabled else "mock",
        ip_hash=keyed_hash(client_ip(request)),
        intake={},
        last_message_at=now,
    )
    db.add(conv)
    db.commit()
    return {"token": token, "greeting": GREETING, "mode": conv.ai_mode}


@router.get("/conversation")
def current(db: Session = Depends(get_db), x_conversation_token: str | None = Header(default=None)):
    conv = _conversation(db, x_conversation_token)
    pending = None
    if conv.status == "esperando_confirmacion" and conv.pending_summary:
        pending = summary_lines(db, conv.pending_summary)
    return {
        "greeting": GREETING,
        "mode": conv.ai_mode,
        "status": conv.status,
        "messages": _public_messages(conv),
        "pending_confirmation": pending,
    }


def _guard_turn(request: Request, conv: Conversation) -> None:
    settings = get_settings()
    enforce(request, "chat-ip", limit=60, window_seconds=600)
    enforce(request, "chat-conv", limit=15, window_seconds=60, key=str(conv.id))
    if conv.message_count >= settings.chat_max_messages_per_conversation:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Esta conversación alcanzó su límite de mensajes. Puede iniciar una nueva o contactar al taller.",
        )


def _turn(db: Session, conv: Conversation, **kwargs) -> dict:
    try:
        result = run_turn(db, conv, **kwargs)
    except BudgetExceeded as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return {**result, "mode": conv.ai_mode}


@router.post("/messages")
def send_message(
    body: MessageIn,
    request: Request,
    db: Session = Depends(get_db),
    x_conversation_token: str | None = Header(default=None),
):
    conv = _conversation(db, x_conversation_token)
    text = body.message.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "El mensaje está vacío.")
    if len(text) > get_settings().chat_max_message_chars:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "El mensaje es demasiado extenso.")
    _guard_turn(request, conv)
    return _turn(db, conv, user_text=text)


@router.post("/confirm")
def confirm(request: Request, db: Session = Depends(get_db), x_conversation_token: str | None = Header(default=None)):
    conv = _conversation(db, x_conversation_token)
    _guard_turn(request, conv)
    if conv.status != "esperando_confirmacion" or not conv.pending_summary:
        raise HTTPException(status.HTTP_409_CONFLICT, "No hay un resumen pendiente de confirmación.")
    current_data = {k: v for k, v in (conv.intake or {}).items() if not k.startswith("_")}
    if current_data != conv.pending_summary:
        raise HTTPException(status.HTTP_409_CONFLICT, "Los datos cambiaron. Revise el nuevo resumen.")
    conv.confirmed_snapshot = dict(conv.pending_summary)
    conv.confirmed_at = utcnow()
    conv.pending_summary = None
    conv.status = "activa"
    db.commit()
    return _turn(db, conv, event="confirmado. El cliente presionó Confirmar sobre el resumen presentado.")
