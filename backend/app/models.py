"""Modelo relacional de Signature Auto Repair.

Todas las fechas se guardan en UTC sin zona horaria. Los valores de estado se guardan como texto
con restricciones CHECK para que el esquema sea portable entre SQLite y PostgreSQL.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utcnow

REQUEST_STATUSES = (
    "nueva",
    "en_revision",
    "esperando_informacion",
    "contactado",
    "presupuesto_pendiente",
    "aprobado",
    "rechazado",
    "finalizado",
)
REQUEST_OPEN_STATUSES = REQUEST_STATUSES[:5]
APPOINTMENT_STATUSES = ("solicitado", "confirmado", "cancelado", "completado", "ausente")
APPOINTMENT_ACTIVE_STATUSES = ("solicitado", "confirmado")
CONTACT_CHANNELS = ("telefono", "whatsapp", "email")
FOLLOWUP_STATUSES = ("borrador", "aprobado", "enviado", "descartado")
FOLLOWUP_KINDS = ("mensaje", "llamada", "email", "whatsapp", "nota")
CONVERSATION_STATUSES = ("activa", "esperando_confirmacion", "registrada", "cerrada")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class AdminUser(TimestampMixin, Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)

    sessions: Mapped[list["AdminSession"]] = relationship(back_populates="admin", cascade="all, delete-orphan")


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))

    admin: Mapped[AdminUser] = relationship(back_populates="sessions")


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (
        CheckConstraint(_in("preferred_contact", CONTACT_CHANNELS) + " OR preferred_contact IS NULL", name="ck_customer_contact"),
        Index("ix_customers_phone", "phone_normalized"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40))
    phone_normalized: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    preferred_contact: Mapped[str | None] = mapped_column(String(16))
    internal_notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="asistente", nullable=False)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime)
    consent_version: Mapped[str | None] = mapped_column(String(20))

    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="customer", cascade="all, delete-orphan")
    requests: Mapped[list["ServiceRequest"]] = relationship(back_populates="customer")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="customer")


class Vehicle(TimestampMixin, Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        CheckConstraint("year IS NULL OR (year >= 1900 AND year <= 2100)", name="ck_vehicle_year"),
        CheckConstraint("mileage_km IS NULL OR mileage_km >= 0", name="ck_vehicle_mileage"),
        UniqueConstraint("plate", name="uq_vehicle_plate"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    make: Mapped[str] = mapped_column(String(60), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    year: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[str | None] = mapped_column(String(80))
    mileage_km: Mapped[int | None] = mapped_column(Integer)
    plate: Mapped[str | None] = mapped_column(String(12))
    vin: Mapped[str | None] = mapped_column(String(17))

    customer: Mapped[Customer] = relationship(back_populates="vehicles")
    requests: Mapped[list["ServiceRequest"]] = relationship(back_populates="vehicle")


class Service(TimestampMixin, Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Texto de precio configurado por el taller (por ejemplo "Desde ARS ..."). Nulo = a cotizar.
    price_info: Mapped[str | None] = mapped_column(String(120))
    additional_info: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (CheckConstraint(_in("status", CONVERSATION_STATUSES), name="ck_conversation_status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="activa", nullable=False)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"), index=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"))
    # Datos recopilados por el asistente, aún no confirmados por el cliente.
    intake: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    # Resumen presentado al cliente y pendiente de confirmación (copia inmutable de intake).
    pending_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    confirmed_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    consent_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consent_version: Mapped[str] = mapped_column(String(20), nullable=False)
    ai_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lookup_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.id"
    )
    customer: Mapped[Customer | None] = relationship()
    requests: Mapped[list["ServiceRequest"]] = relationship(back_populates="conversation")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (CheckConstraint(_in("role", ("user", "assistant", "tool", "event")), name="ck_message_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(60))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class ServiceRequest(TimestampMixin, Base):
    __tablename__ = "service_requests"
    __table_args__ = (
        CheckConstraint(_in("status", REQUEST_STATUSES), name="ck_request_status"),
        CheckConstraint(
            "frequency IS NULL OR " + _in("frequency", ("constante", "intermitente", "no_sabe")),
            name="ck_request_frequency",
        ),
        Index("ix_requests_status_activity", "status", "last_activity_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"), index=True)
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id", ondelete="SET NULL"))
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), unique=True
    )
    status: Mapped[str] = mapped_column(String(30), default="nueva", nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="asistente", nullable=False)
    requested_service: Mapped[str | None] = mapped_column(String(120))
    problem_description: Mapped[str | None] = mapped_column(Text)
    symptoms: Mapped[str | None] = mapped_column(Text)
    onset: Mapped[str | None] = mapped_column(String(200))
    frequency: Mapped[str | None] = mapped_column(String(20))
    customer_availability: Mapped[str | None] = mapped_column(String(300))
    preferred_date: Mapped[str | None] = mapped_column(String(120))
    additional_notes: Mapped[str | None] = mapped_column(Text)
    extra_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    quote_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    quote_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="requests")
    vehicle: Mapped[Vehicle | None] = relationship(back_populates="requests")
    service: Mapped[Service | None] = relationship()
    conversation: Mapped[Conversation | None] = relationship(back_populates="requests")
    notes: Mapped[list["InternalNote"]] = relationship(back_populates="service_request", order_by="InternalNote.id")
    follow_ups: Mapped[list["FollowUp"]] = relationship(back_populates="service_request", order_by="FollowUp.id")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="service_request")


class Appointment(TimestampMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint(_in("status", APPOINTMENT_STATUSES), name="ck_appointment_status"),
        CheckConstraint("end_at > start_at", name="ck_appointment_range"),
        Index("ix_appointments_range", "start_at", "end_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"))
    service_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_requests.id", ondelete="SET NULL"), index=True
    )
    start_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="solicitado", nullable=False)
    created_by: Mapped[str] = mapped_column(String(20), default="asistente", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    customer: Mapped[Customer] = relationship(back_populates="appointments")
    vehicle: Mapped[Vehicle | None] = relationship()
    service_request: Mapped[ServiceRequest | None] = relationship(back_populates="appointments")


class InternalNote(Base):
    __tablename__ = "internal_notes"
    __table_args__ = (
        CheckConstraint("service_request_id IS NOT NULL OR customer_id IS NOT NULL", name="ck_note_target"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    service_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_requests.id", ondelete="CASCADE"), index=True
    )
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    service_request: Mapped[ServiceRequest | None] = relationship(back_populates="notes")
    author: Mapped[AdminUser | None] = relationship()


class FollowUp(TimestampMixin, Base):
    """Acción de seguimiento comercial. Un borrador generado nunca se considera enviado
    hasta que el administrador lo aprueba y registra el envío."""

    __tablename__ = "follow_ups"
    __table_args__ = (
        CheckConstraint(_in("status", FOLLOWUP_STATUSES), name="ck_followup_status"),
        CheckConstraint(_in("kind", FOLLOWUP_KINDS), name="ck_followup_kind"),
        CheckConstraint("customer_id IS NOT NULL OR conversation_id IS NOT NULL", name="ck_followup_target"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    # Visitantes que dejaron datos en el asistente pero no completaron la solicitud.
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    service_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_requests.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20), default="mensaje", nullable=False)
    reason: Mapped[str | None] = mapped_column(String(60))
    channel: Mapped[str | None] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Sugerencia interna para el personal (no se envía al cliente).
    suggestion: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="borrador", nullable=False)
    generated_by: Mapped[str] = mapped_column(String(20), default="admin", nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)

    customer: Mapped[Customer | None] = relationship()
    conversation: Mapped[Conversation | None] = relationship()
    service_request: Mapped[ServiceRequest | None] = relationship(back_populates="follow_ups")


class BusinessSettings(TimestampMixin, Base):
    """Fila única (id=1) con la configuración operativa del taller."""

    __tablename__ = "business_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_name: Mapped[str] = mapped_column(String(120), default="Signature Auto Repair", nullable=False)
    # Datos de contacto: los valores iniciales son provisionales y se marcan como tales.
    contact: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="America/Argentina/Buenos_Aires", nullable=False)
    # {"0": [["09:00","18:00"]], ...} con 0 = lunes.
    weekly_schedule: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    closed_dates: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    slot_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    bays: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    min_notice_hours: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    booking_horizon_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    stale_after_days: Mapped[int] = mapped_column(Integer, default=3, nullable=False)


class AIUsage(Base):
    __tablename__ = "ai_usage"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    requests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)  # admin | asistente | sistema
    actor_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    entity: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
