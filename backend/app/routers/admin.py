import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.ai.orchestrator import BudgetExceeded
from app.ai.providers import ProviderError
from app.config import get_settings
from app.db import get_db, utcnow
from app.deps import iso, require_admin
from app.models import (
    APPOINTMENT_ACTIVE_STATUSES,
    APPOINTMENT_STATUSES,
    REQUEST_OPEN_STATUSES,
    REQUEST_STATUSES,
    AdminSession,
    AIUsage,
    Appointment,
    AuditLog,
    Conversation,
    Customer,
    FollowUp,
    InternalNote,
    Service,
    ServiceRequest,
    Vehicle,
)
from app.security import audit
from app.services import intake as intake_svc
from app.services.admin_ai import generate_follow_up, generate_request_summary
from app.services.availability import free_slots, overlapping_count, to_local, to_utc, within_schedule
from app.services.business import get_business_settings
from app.services.opportunities import detect
from app.services.registry import (
    RegistryError,
    book_appointment,
    booking_lock,
    create_service_request,
    get_or_create_customer,
    get_or_create_vehicle,
)

router = APIRouter(prefix="/api/admin", tags=["administración"], dependencies=[Depends(require_admin)])

ContactChannel = Literal["telefono", "whatsapp", "email"]


def _like(term: str) -> str:
    escaped = term.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _admin_id(request: Request) -> int:
    return request.state.admin_id


def _page(query, db: Session, page: int, page_size: int):
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    items = db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    return items, total


def _get(db: Session, model, entity_id: int):
    obj = db.get(model, entity_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Registro no encontrado.")
    return obj


# --- Serialización ---------------------------------------------------------------------------------


def customer_out(c: Customer) -> dict[str, Any]:
    return {
        "id": c.id,
        "full_name": c.full_name,
        "phone": c.phone,
        "email": c.email,
        "preferred_contact": c.preferred_contact,
        "source": c.source,
        "internal_notes": c.internal_notes,
        "created_at": iso(c.created_at),
        "consent_at": iso(c.consent_at),
    }


def vehicle_out(v: Vehicle) -> dict[str, Any]:
    return {
        "id": v.id,
        "customer_id": v.customer_id,
        "customer_name": v.customer.full_name,
        "make": v.make,
        "model": v.model,
        "year": v.year,
        "version": v.version,
        "mileage_km": v.mileage_km,
        "plate": v.plate,
        "vin": v.vin,
        "created_at": iso(v.created_at),
    }


def request_out(r: ServiceRequest) -> dict[str, Any]:
    return {
        "id": r.id,
        "code": r.code,
        "status": r.status,
        "source": r.source,
        "created_at": iso(r.created_at),
        "updated_at": iso(r.updated_at),
        "last_activity_at": iso(r.last_activity_at),
        "customer": {"id": r.customer.id, "full_name": r.customer.full_name, "phone": r.customer.phone, "email": r.customer.email},
        "vehicle": (
            {"id": r.vehicle.id, "make": r.vehicle.make, "model": r.vehicle.model, "year": r.vehicle.year,
             "version": r.vehicle.version, "mileage_km": r.vehicle.mileage_km, "plate": r.vehicle.plate}
            if r.vehicle else None
        ),
        "requested_service": r.requested_service,
        "problem_description": r.problem_description,
        "quote_amount": float(r.quote_amount) if r.quote_amount is not None else None,
    }


def appointment_out(a: Appointment, tz: str) -> dict[str, Any]:
    return {
        "id": a.id,
        "start_at": iso(a.start_at),
        "end_at": iso(a.end_at),
        "start_local": to_local(a.start_at, tz).strftime("%Y-%m-%dT%H:%M"),
        "end_local": to_local(a.end_at, tz).strftime("%Y-%m-%dT%H:%M"),
        "status": a.status,
        "created_by": a.created_by,
        "notes": a.notes,
        "customer": {"id": a.customer.id, "full_name": a.customer.full_name, "phone": a.customer.phone},
        "vehicle": {"id": a.vehicle.id, "label": f"{a.vehicle.make} {a.vehicle.model}"} if a.vehicle else None,
        "request": {"id": a.service_request.id, "code": a.service_request.code} if a.service_request else None,
    }


def follow_up_out(f: FollowUp) -> dict[str, Any]:
    return {
        "id": f.id,
        "kind": f.kind,
        "reason": f.reason,
        "channel": f.channel,
        "message": f.message,
        "suggestion": f.suggestion,
        "status": f.status,
        "generated_by": f.generated_by,
        "customer_id": f.customer_id,
        "conversation_id": f.conversation_id,
        "service_request_id": f.service_request_id,
        "created_at": iso(f.created_at),
        "approved_at": iso(f.approved_at),
        "sent_at": iso(f.sent_at),
    }


# --- Dashboard -------------------------------------------------------------------------------------


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    now = utcnow()
    count = lambda q: db.scalar(q) or 0  # noqa: E731
    by_status = dict(db.execute(select(ServiceRequest.status, func.count()).group_by(ServiceRequest.status)).all())
    since = now - timedelta(days=13)
    daily_rows = db.execute(
        select(func.date(ServiceRequest.created_at), func.count())
        .where(ServiceRequest.created_at >= since.replace(hour=0, minute=0, second=0))
        .group_by(func.date(ServiceRequest.created_at))
    ).all()
    daily_map = {str(d): n for d, n in daily_rows}
    daily = [
        {"date": (since.date() + timedelta(days=i)).isoformat(), "count": daily_map.get((since.date() + timedelta(days=i)).isoformat(), 0)}
        for i in range(14)
    ]
    by_service = db.execute(
        select(func.coalesce(ServiceRequest.requested_service, "Sin servicio asignado"), func.count())
        .group_by(ServiceRequest.requested_service)
        .order_by(func.count().desc())
        .limit(8)
    ).all()
    opportunities = detect(db)
    usage = db.get(AIUsage, now.date())
    return {
        "metrics": {
            "conversations_total": count(select(func.count(Conversation.id))),
            "requests_total": sum(by_status.values()),
            "requests_new": by_status.get("nueva", 0),
            "requests_pending": sum(by_status.get(s, 0) for s in REQUEST_OPEN_STATUSES),
            "appointments_requested": count(
                select(func.count(Appointment.id)).where(Appointment.status == "solicitado", Appointment.end_at >= now)
            ),
            "appointments_confirmed": count(
                select(func.count(Appointment.id)).where(Appointment.status == "confirmado", Appointment.end_at >= now)
            ),
            "quotes_pending": by_status.get("presupuesto_pendiente", 0),
            "customers_total": count(select(func.count(Customer.id))),
            "opportunities_unattended": sum(1 for o in opportunities if not o["last_follow_up"]),
        },
        "requests_by_status": [{"status": s, "count": by_status.get(s, 0)} for s in REQUEST_STATUSES],
        "requests_daily": daily,
        "requests_by_service": [{"service": s, "count": n} for s, n in by_service],
        "recent_requests": [
            request_out(r)
            for r in db.scalars(select(ServiceRequest).order_by(ServiceRequest.created_at.desc()).limit(6)).all()
        ],
        "ai": {
            "mode": "openai" if get_settings().ai_enabled else "mock",
            "model": get_settings().openai_model if get_settings().ai_enabled else None,
            "requests_today": usage.requests if usage else 0,
            "tokens_today": (usage.input_tokens + usage.output_tokens) if usage else 0,
        },
    }


# --- Consultas / solicitudes ----------------------------------------------------------------------


@router.get("/requests")
def list_requests(
    db: Session = Depends(get_db),
    status_filter: str | None = Query(default=None, alias="status", max_length=30),
    q: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=25, ge=1, le=100),
):
    query = select(ServiceRequest).join(Customer).outerjoin(Vehicle, ServiceRequest.vehicle_id == Vehicle.id)
    if status_filter == "abiertas":
        query = query.where(ServiceRequest.status.in_(REQUEST_OPEN_STATUSES))
    elif status_filter:
        if status_filter not in REQUEST_STATUSES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Estado inválido.")
        query = query.where(ServiceRequest.status == status_filter)
    if q:
        term = _like(q)
        query = query.where(
            or_(
                ServiceRequest.code.ilike(term, escape="\\"),
                Customer.full_name.ilike(term, escape="\\"),
                Customer.email.ilike(term, escape="\\"),
                Customer.phone.ilike(term, escape="\\"),
                Vehicle.make.ilike(term, escape="\\"),
                Vehicle.model.ilike(term, escape="\\"),
                Vehicle.plate.ilike(term, escape="\\"),
            )
        )
    items, total = _page(query.order_by(ServiceRequest.created_at.desc()), db, page, page_size)
    return {"items": [request_out(r) for r in items], "total": total, "page": page, "page_size": page_size}


@router.get("/requests/{request_id}")
def get_request(request_id: int, db: Session = Depends(get_db)):
    r = _get(db, ServiceRequest, request_id)
    tz = get_business_settings(db).timezone
    conversation = None
    if r.conversation:
        conversation = {
            "id": r.conversation.id,
            "mode": r.conversation.ai_mode,
            "consent_at": iso(r.conversation.consent_at),
            "consent_version": r.conversation.consent_version,
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "tool_name": m.tool_name,
                    "ok": (m.payload or {}).get("ok") if m.role == "tool" else None,
                    "created_at": iso(m.created_at),
                }
                for m in r.conversation.messages
            ],
        }
    return {
        **request_out(r),
        "customer": customer_out(r.customer),
        "service_id": r.service_id,
        "symptoms": r.symptoms,
        "onset": r.onset,
        "frequency": r.frequency,
        "customer_availability": r.customer_availability,
        "preferred_date": r.preferred_date,
        "additional_notes": r.additional_notes,
        "extra_data": r.extra_data,
        "ai_summary": r.ai_summary,
        "quote_sent_at": iso(r.quote_sent_at),
        "notes": [
            {"id": n.id, "body": n.body, "author": n.author.full_name if n.author else None, "created_at": iso(n.created_at)}
            for n in r.notes
        ],
        "follow_ups": [follow_up_out(f) for f in r.follow_ups],
        "appointments": [appointment_out(a, tz) for a in r.appointments],
        "conversation": conversation,
    }


class RequestPatch(BaseModel):
    status: Literal[REQUEST_STATUSES] | None = None  # type: ignore[valid-type]
    quote_amount: Decimal | None = Field(default=None, ge=0, le=Decimal("999999999"))
    quote_sent: bool | None = None
    ai_summary: str | None = Field(default=None, max_length=4000)
    service_id: int | None = None


@router.patch("/requests/{request_id}")
def update_request(request_id: int, body: RequestPatch, request: Request, db: Session = Depends(get_db)):
    r = _get(db, ServiceRequest, request_id)
    changes: dict[str, Any] = {}
    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] and data["status"] != r.status:
        changes["status"] = [r.status, data["status"]]
        r.status = data["status"]
    if "quote_amount" in data:
        r.quote_amount = data["quote_amount"]
        changes["quote_amount"] = str(data["quote_amount"])
    if data.get("quote_sent"):
        r.quote_sent_at = utcnow()
        changes["quote_sent"] = True
    if "ai_summary" in data:
        r.ai_summary = intake_svc.clean_text(data["ai_summary"], 4000)
    if "service_id" in data:
        service = _get(db, Service, data["service_id"]) if data["service_id"] else None
        r.service_id = service.id if service else None
        r.requested_service = service.name if service else r.requested_service
    r.last_activity_at = utcnow()
    audit(db, "admin", "request_updated", actor_id=_admin_id(request), entity="service_request", entity_id=r.id, details=changes)
    db.commit()
    return get_request(r.id, db)


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


@router.post("/requests/{request_id}/notes", status_code=201)
def add_request_note(request_id: int, body: NoteIn, request: Request, db: Session = Depends(get_db)):
    r = _get(db, ServiceRequest, request_id)
    note = InternalNote(service_request_id=r.id, author_id=_admin_id(request), body=body.body.strip())
    db.add(note)
    r.last_activity_at = utcnow()
    db.commit()
    return {"id": note.id}


class ActionIn(BaseModel):
    kind: Literal["llamada", "email", "whatsapp", "nota"]
    message: str = Field(min_length=1, max_length=4000)


@router.post("/requests/{request_id}/actions", status_code=201)
def log_action(request_id: int, body: ActionIn, request: Request, db: Session = Depends(get_db)):
    """Registra una acción de seguimiento ya realizada por el personal (por ejemplo, una llamada)."""
    r = _get(db, ServiceRequest, request_id)
    now = utcnow()
    action = FollowUp(
        customer_id=r.customer_id,
        service_request_id=r.id,
        kind=body.kind,
        channel=body.kind if body.kind != "nota" else None,
        message=body.message.strip(),
        status="enviado",
        generated_by="admin",
        created_by_id=_admin_id(request),
        approved_at=now,
        sent_at=now,
    )
    db.add(action)
    r.last_activity_at = now
    db.commit()
    return follow_up_out(action)


@router.post("/requests/{request_id}/summary")
def regenerate_summary(request_id: int, request: Request, db: Session = Depends(get_db)):
    r = _get(db, ServiceRequest, request_id)
    try:
        summary, source = generate_request_summary(db, r)
    except (ProviderError, BudgetExceeded) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    r.ai_summary = summary
    audit(db, "admin", "summary_generated", actor_id=_admin_id(request), entity="service_request", entity_id=r.id, details={"source": source})
    db.commit()
    return {"ai_summary": summary, "generated_by": source}


class ManualRequestIn(BaseModel):
    customer_id: int | None = None
    full_name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    email: EmailStr | None = None
    preferred_contact: ContactChannel | None = None
    vehicle_id: int | None = None
    make: str | None = Field(default=None, max_length=60)
    model: str | None = Field(default=None, max_length=80)
    year: int | None = Field(default=None, ge=1950, le=2100)
    mileage_km: int | None = Field(default=None, ge=0, le=2_000_000)
    plate: str | None = Field(default=None, max_length=12)
    service_id: int | None = None
    problem_description: str = Field(min_length=3, max_length=1500)
    additional_notes: str | None = Field(default=None, max_length=1000)


@router.post("/requests", status_code=201)
def create_manual_request(body: ManualRequestIn, request: Request, db: Session = Depends(get_db)):
    if body.customer_id:
        customer = _get(db, Customer, body.customer_id)
    else:
        if not body.full_name or not (body.phone or body.email):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Indique nombre y un dato de contacto.")
        customer, _, _ = get_or_create_customer(
            db, body.model_dump(), source="panel", consent_at=None, consent_version=None
        )
    vehicle = None
    if body.vehicle_id:
        vehicle = _get(db, Vehicle, body.vehicle_id)
        if vehicle.customer_id != customer.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "El vehículo no pertenece al cliente.")
    elif body.make and body.model:
        plate = intake_svc.normalize_plate(body.plate) if body.plate else None
        vehicle, _, _ = get_or_create_vehicle(db, customer, {**body.model_dump(), "plate": plate})
    service = _get(db, Service, body.service_id) if body.service_id else None
    r = create_service_request(
        db,
        customer=customer,
        vehicle=vehicle,
        data={"service_slug": service.slug if service else None, "problem_description": body.problem_description,
              "additional_notes": body.additional_notes},
        source="panel",
    )
    audit(db, "admin", "request_created", actor_id=_admin_id(request), entity="service_request", entity_id=r.id)
    db.commit()
    return {"id": r.id, "code": r.code}


# --- Clientes ------------------------------------------------------------------------------------


@router.get("/customers")
def list_customers(
    db: Session = Depends(get_db),
    q: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=25, ge=1, le=100),
):
    query = select(Customer)
    if q:
        term = _like(q)
        query = query.where(
            or_(
                Customer.full_name.ilike(term, escape="\\"),
                Customer.email.ilike(term, escape="\\"),
                Customer.phone.ilike(term, escape="\\"),
            )
        )
    items, total = _page(query.order_by(Customer.created_at.desc()), db, page, page_size)
    return {
        "items": [
            {**customer_out(c), "vehicles_count": len(c.vehicles), "requests_count": len(c.requests)} for c in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/customers/{customer_id}")
def get_customer(customer_id: int, db: Session = Depends(get_db)):
    c = _get(db, Customer, customer_id)
    tz = get_business_settings(db).timezone
    notes = db.scalars(select(InternalNote).where(InternalNote.customer_id == c.id).order_by(InternalNote.id)).all()
    return {
        **customer_out(c),
        "vehicles": [vehicle_out(v) for v in c.vehicles],
        "requests": [request_out(r) for r in sorted(c.requests, key=lambda r: r.created_at, reverse=True)],
        "appointments": [appointment_out(a, tz) for a in sorted(c.appointments, key=lambda a: a.start_at, reverse=True)],
        "notes": [{"id": n.id, "body": n.body, "created_at": iso(n.created_at)} for n in notes],
    }


def _valid_phone(value: str | None) -> str | None:
    if value and not intake_svc.normalize_phone(value):
        raise ValueError("El teléfono debe tener entre 8 y 15 dígitos.")
    return value


class CustomerIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    email: EmailStr | None = None
    preferred_contact: ContactChannel | None = None
    internal_notes: str | None = Field(default=None, max_length=4000)

    _phone = field_validator("phone")(_valid_phone)


class CustomerPatch(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    email: EmailStr | None = None
    preferred_contact: ContactChannel | None = None
    internal_notes: str | None = Field(default=None, max_length=4000)

    _phone = field_validator("phone")(_valid_phone)


def _apply_customer(db: Session, c: Customer, data: dict[str, Any]) -> None:
    if "email" in data:
        email = data["email"].lower() if data["email"] else None
        if email and db.scalar(select(Customer.id).where(Customer.email == email, Customer.id != c.id)):
            raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe otro cliente con ese correo electrónico.")
        c.email = email
    if "phone" in data:
        c.phone = data["phone"]
        c.phone_normalized = intake_svc.normalize_phone(data["phone"]) if data["phone"] else None
    for field in ("full_name", "preferred_contact", "internal_notes"):
        if field in data:
            setattr(c, field, data[field])


@router.post("/customers", status_code=201)
def create_customer(body: CustomerIn, request: Request, db: Session = Depends(get_db)):
    c = Customer(full_name=body.full_name, source="panel")
    db.add(c)
    _apply_customer(db, c, body.model_dump())
    db.flush()
    audit(db, "admin", "customer_created", actor_id=_admin_id(request), entity="customer", entity_id=c.id)
    db.commit()
    return customer_out(c)


@router.patch("/customers/{customer_id}")
def update_customer(customer_id: int, body: CustomerPatch, request: Request, db: Session = Depends(get_db)):
    c = _get(db, Customer, customer_id)
    _apply_customer(db, c, body.model_dump(exclude_unset=True))
    audit(db, "admin", "customer_updated", actor_id=_admin_id(request), entity="customer", entity_id=c.id)
    db.commit()
    return customer_out(c)


@router.post("/customers/{customer_id}/notes", status_code=201)
def add_customer_note(customer_id: int, body: NoteIn, request: Request, db: Session = Depends(get_db)):
    c = _get(db, Customer, customer_id)
    note = InternalNote(customer_id=c.id, author_id=_admin_id(request), body=body.body.strip())
    db.add(note)
    db.commit()
    return {"id": note.id}


# --- Vehículos -----------------------------------------------------------------------------------


@router.get("/vehicles")
def list_vehicles(
    db: Session = Depends(get_db),
    q: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=25, ge=1, le=100),
):
    query = select(Vehicle).join(Customer)
    if q:
        term = _like(q)
        query = query.where(
            or_(
                Vehicle.make.ilike(term, escape="\\"),
                Vehicle.model.ilike(term, escape="\\"),
                Vehicle.plate.ilike(term, escape="\\"),
                Vehicle.vin.ilike(term, escape="\\"),
                Customer.full_name.ilike(term, escape="\\"),
            )
        )
    items, total = _page(query.order_by(Vehicle.created_at.desc()), db, page, page_size)
    return {
        "items": [{**vehicle_out(v), "requests_count": len(v.requests)} for v in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/vehicles/{vehicle_id}")
def get_vehicle(vehicle_id: int, db: Session = Depends(get_db)):
    v = _get(db, Vehicle, vehicle_id)
    return {**vehicle_out(v), "requests": [request_out(r) for r in sorted(v.requests, key=lambda r: r.created_at, reverse=True)]}


class VehicleIn(BaseModel):
    customer_id: int
    make: str = Field(min_length=1, max_length=60)
    model: str = Field(min_length=1, max_length=80)
    year: int | None = Field(default=None, ge=1950, le=2100)
    version: str | None = Field(default=None, max_length=80)
    mileage_km: int | None = Field(default=None, ge=0, le=2_000_000)
    plate: str | None = Field(default=None, max_length=12)
    vin: str | None = Field(default=None, max_length=17)


class VehiclePatch(BaseModel):
    make: str | None = Field(default=None, min_length=1, max_length=60)
    model: str | None = Field(default=None, min_length=1, max_length=80)
    year: int | None = Field(default=None, ge=1950, le=2100)
    version: str | None = Field(default=None, max_length=80)
    mileage_km: int | None = Field(default=None, ge=0, le=2_000_000)
    plate: str | None = Field(default=None, max_length=12)
    vin: str | None = Field(default=None, max_length=17)


def _apply_vehicle(db: Session, v: Vehicle, data: dict[str, Any]) -> None:
    if data.get("plate"):
        plate = intake_svc.normalize_plate(data["plate"])
        if not plate:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Patente inválida.")
        if db.scalar(select(Vehicle.id).where(Vehicle.plate == plate, Vehicle.id != (v.id or 0))):
            raise HTTPException(status.HTTP_409_CONFLICT, "La patente ya está registrada en otro vehículo.")
        data["plate"] = plate
    if data.get("vin"):
        vin = intake_svc.normalize_vin(data["vin"])
        if not vin:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "VIN inválido.")
        data["vin"] = vin
    for field, value in data.items():
        if field != "customer_id":
            setattr(v, field, value.strip() if isinstance(value, str) else value)


@router.post("/vehicles", status_code=201)
def create_vehicle(body: VehicleIn, request: Request, db: Session = Depends(get_db)):
    customer = _get(db, Customer, body.customer_id)
    v = Vehicle(customer_id=customer.id, make=body.make, model=body.model)
    _apply_vehicle(db, v, body.model_dump())
    db.add(v)
    db.flush()
    audit(db, "admin", "vehicle_created", actor_id=_admin_id(request), entity="vehicle", entity_id=v.id)
    db.commit()
    return vehicle_out(v)


@router.patch("/vehicles/{vehicle_id}")
def update_vehicle(vehicle_id: int, body: VehiclePatch, request: Request, db: Session = Depends(get_db)):
    v = _get(db, Vehicle, vehicle_id)
    _apply_vehicle(db, v, body.model_dump(exclude_unset=True))
    audit(db, "admin", "vehicle_updated", actor_id=_admin_id(request), entity="vehicle", entity_id=v.id)
    db.commit()
    return vehicle_out(v)


# --- Turnos --------------------------------------------------------------------------------------


def _parse_local(value: str, tz: str) -> datetime:
    try:
        return to_utc(datetime.strptime(value[:16], "%Y-%m-%dT%H:%M"), tz)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Formato de fecha y hora inválido.") from exc


@router.get("/appointments")
def list_appointments(
    db: Session = Depends(get_db),
    date_from: date = Query(alias="from"),
    date_to: date = Query(alias="to"),
    include_cancelled: bool = False,
):
    if (date_to - date_from).days > 62 or date_to < date_from:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Rango de fechas inválido (máximo 62 días).")
    tz = get_business_settings(db).timezone
    start = to_utc(datetime.combine(date_from, datetime.min.time()), tz)
    end = to_utc(datetime.combine(date_to + timedelta(days=1), datetime.min.time()), tz)
    query = select(Appointment).where(Appointment.start_at < end, Appointment.end_at > start)
    if not include_cancelled:
        query = query.where(Appointment.status != "cancelado")
    items = db.scalars(query.order_by(Appointment.start_at)).all()
    return {"items": [appointment_out(a, tz) for a in items], "timezone": tz}


@router.get("/availability")
def availability(
    db: Session = Depends(get_db),
    date_from: date = Query(alias="from"),
    days: int = Query(default=7, ge=1, le=31),
):
    settings = get_business_settings(db)
    slots = free_slots(db, settings, date_from, days, limit=200, enforce_notice=False)
    return {
        "timezone": settings.timezone,
        "slot_minutes": settings.slot_minutes,
        "slots": [to_local(s.start, settings.timezone).strftime("%Y-%m-%dT%H:%M") for s in slots],
    }


class AppointmentIn(BaseModel):
    customer_id: int
    vehicle_id: int | None = None
    service_request_id: int | None = None
    start_local: str = Field(max_length=16)
    end_local: str | None = Field(default=None, max_length=16)
    status: Literal["solicitado", "confirmado"] = "confirmado"
    notes: str | None = Field(default=None, max_length=2000)
    allow_outside_schedule: bool = False


class AppointmentPatch(BaseModel):
    start_local: str | None = Field(default=None, max_length=16)
    end_local: str | None = Field(default=None, max_length=16)
    status: Literal[APPOINTMENT_STATUSES] | None = None  # type: ignore[valid-type]
    notes: str | None = Field(default=None, max_length=2000)
    allow_outside_schedule: bool = False


@router.post("/appointments", status_code=201)
def create_appointment(body: AppointmentIn, request: Request, db: Session = Depends(get_db)):
    tz = get_business_settings(db).timezone
    customer = _get(db, Customer, body.customer_id)
    if body.vehicle_id and _get(db, Vehicle, body.vehicle_id).customer_id != customer.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "El vehículo no pertenece al cliente.")
    if body.service_request_id and _get(db, ServiceRequest, body.service_request_id).customer_id != customer.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "La solicitud no pertenece al cliente.")
    start = _parse_local(body.start_local, tz)
    end = _parse_local(body.end_local, tz) if body.end_local else None
    try:
        a = book_appointment(
            db,
            customer_id=customer.id,
            vehicle_id=body.vehicle_id,
            service_request_id=body.service_request_id,
            start=start,
            end=end,
            status=body.status,
            created_by="panel",
            notes=body.notes,
            allow_outside_schedule=body.allow_outside_schedule,
        )
    except RegistryError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    audit(db, "admin", "appointment_created", actor_id=_admin_id(request), entity="appointment", entity_id=a.id)
    db.commit()
    return appointment_out(a, tz)


@router.patch("/appointments/{appointment_id}")
def update_appointment(appointment_id: int, body: AppointmentPatch, request: Request, db: Session = Depends(get_db)):
    settings = get_business_settings(db)
    a = _get(db, Appointment, appointment_id)
    data = body.model_dump(exclude_unset=True)
    new_start = _parse_local(data["start_local"], settings.timezone) if data.get("start_local") else a.start_at
    if data.get("end_local"):
        new_end = _parse_local(data["end_local"], settings.timezone)
    elif data.get("start_local"):
        new_end = new_start + (a.end_at - a.start_at)
    else:
        new_end = a.end_at
    new_status = data.get("status") or a.status
    reactivating = new_status in APPOINTMENT_ACTIVE_STATUSES and (
        new_start != a.start_at or new_end != a.end_at or a.status not in APPOINTMENT_ACTIVE_STATUSES
    )
    if reactivating:
        with booking_lock:
            if new_end <= new_start:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "El fin debe ser posterior al inicio.")
            if not body.allow_outside_schedule and not within_schedule(settings, new_start, new_end):
                raise HTTPException(status.HTTP_409_CONFLICT, "El horario está fuera de la agenda de atención.")
            if overlapping_count(db, new_start, new_end, exclude_id=a.id) >= settings.bays:
                raise HTTPException(status.HTTP_409_CONFLICT, "El horario se superpone con otro turno.")
            a.start_at, a.end_at = new_start, new_end
    elif new_start != a.start_at or new_end != a.end_at:
        a.start_at, a.end_at = new_start, new_end
    changes = {"status": [a.status, new_status]} if new_status != a.status else {}
    a.status = new_status
    if "notes" in data:
        a.notes = data["notes"]
    if a.service_request:
        a.service_request.last_activity_at = utcnow()
    audit(db, "admin", "appointment_updated", actor_id=_admin_id(request), entity="appointment", entity_id=a.id, details=changes)
    db.commit()
    return appointment_out(a, settings.timezone)


# --- Servicios -----------------------------------------------------------------------------------


class ServiceIn(BaseModel):
    slug: str = Field(min_length=2, max_length=60, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(min_length=5, max_length=1000)
    category: str = Field(min_length=2, max_length=60)
    is_active: bool = True
    price_info: str | None = Field(default=None, max_length=120)
    additional_info: str | None = Field(default=None, max_length=2000)
    sort_order: int = Field(default=0, ge=0, le=1000)


class ServicePatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = Field(default=None, min_length=5, max_length=1000)
    category: str | None = Field(default=None, min_length=2, max_length=60)
    is_active: bool | None = None
    price_info: str | None = Field(default=None, max_length=120)
    additional_info: str | None = Field(default=None, max_length=2000)
    sort_order: int | None = Field(default=None, ge=0, le=1000)


def service_out(s: Service) -> dict[str, Any]:
    return {
        "id": s.id, "slug": s.slug, "name": s.name, "description": s.description, "category": s.category,
        "is_active": s.is_active, "price_info": s.price_info, "additional_info": s.additional_info,
        "sort_order": s.sort_order, "updated_at": iso(s.updated_at),
    }


@router.get("/services")
def list_services(db: Session = Depends(get_db)):
    return {"items": [service_out(s) for s in db.scalars(select(Service).order_by(Service.sort_order, Service.name)).all()]}


@router.post("/services", status_code=201)
def create_service(body: ServiceIn, request: Request, db: Session = Depends(get_db)):
    if db.scalar(select(Service.id).where(Service.slug == body.slug)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un servicio con ese identificador.")
    s = Service(**body.model_dump())
    db.add(s)
    db.flush()
    audit(db, "admin", "service_created", actor_id=_admin_id(request), entity="service", entity_id=s.id)
    db.commit()
    return service_out(s)


@router.patch("/services/{service_id}")
def update_service(service_id: int, body: ServicePatch, request: Request, db: Session = Depends(get_db)):
    s = _get(db, Service, service_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(s, field, value)
    audit(db, "admin", "service_updated", actor_id=_admin_id(request), entity="service", entity_id=s.id)
    db.commit()
    return service_out(s)


# --- Configuración del negocio --------------------------------------------------------------------


class ContactIn(BaseModel):
    phone: str = Field(default="", max_length=40)
    whatsapp: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=254)
    address: str = Field(default="", max_length=200)
    city: str = Field(default="", max_length=120)
    hours_text: str = Field(default="", max_length=200)
    maps_url: str = Field(default="", max_length=500, pattern=r"^(https://[^\s]+)?$")
    instagram: str = Field(default="", max_length=200, pattern=r"^(https://[^\s]+)?$")
    is_placeholder: bool = True


class SettingsIn(BaseModel):
    business_name: str = Field(min_length=2, max_length=120)
    contact: ContactIn
    weekly_schedule: dict[Literal["0", "1", "2", "3", "4", "5", "6"], list[tuple[str, str]]]
    closed_dates: list[date] = Field(default_factory=list, max_length=366)
    slot_minutes: int = Field(ge=15, le=480)
    bays: int = Field(ge=1, le=20)
    min_notice_hours: int = Field(ge=0, le=168)
    booking_horizon_days: int = Field(ge=1, le=180)
    stale_after_days: int = Field(ge=1, le=60)

    @field_validator("weekly_schedule")
    @classmethod
    def _schedule(cls, value):
        for blocks in value.values():
            for start, end in blocks:
                if not (re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", start) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", end)):
                    raise ValueError("Los horarios deben tener formato HH:MM.")
                if end <= start:
                    raise ValueError("Cada bloque debe terminar después de comenzar.")
        return value


def settings_out(s) -> dict[str, Any]:
    return {
        "business_name": s.business_name,
        "contact": s.contact,
        "timezone": s.timezone,
        "weekly_schedule": s.weekly_schedule,
        "closed_dates": s.closed_dates,
        "slot_minutes": s.slot_minutes,
        "bays": s.bays,
        "min_notice_hours": s.min_notice_hours,
        "booking_horizon_days": s.booking_horizon_days,
        "stale_after_days": s.stale_after_days,
    }


@router.get("/settings")
def get_settings_endpoint(db: Session = Depends(get_db)):
    return settings_out(get_business_settings(db))


@router.put("/settings")
def update_settings(body: SettingsIn, request: Request, db: Session = Depends(get_db)):
    s = get_business_settings(db)
    data = body.model_dump()
    s.business_name = data["business_name"]
    s.contact = data["contact"]
    s.weekly_schedule = {day: [list(b) for b in blocks] for day, blocks in data["weekly_schedule"].items()}
    for day in map(str, range(7)):
        s.weekly_schedule.setdefault(day, [])
    s.closed_dates = sorted({d.isoformat() for d in data["closed_dates"]})
    for field in ("slot_minutes", "bays", "min_notice_hours", "booking_horizon_days", "stale_after_days"):
        setattr(s, field, data[field])
    audit(db, "admin", "settings_updated", actor_id=_admin_id(request), entity="business_settings", entity_id=1)
    db.commit()
    return settings_out(s)


# --- Radar de oportunidades ------------------------------------------------------------------------


@router.get("/radar")
def radar(db: Session = Depends(get_db)):
    items = detect(db)
    drafts = db.scalars(
        select(FollowUp).where(FollowUp.status.in_(("borrador", "aprobado"))).order_by(FollowUp.created_at.desc())
    ).all()
    return {"items": items, "drafts": [follow_up_out(f) for f in drafts]}


class DraftIn(BaseModel):
    kind: Literal["sin_responder", "incompleta", "presupuesto_pendiente", "turno_sin_confirmar", "aprobado_sin_turno", "sin_actualizacion"]
    request_id: int | None = None
    conversation_id: int | None = None
    customer_id: int | None = None


@router.post("/radar/drafts", status_code=201)
def create_draft(body: DraftIn, request: Request, db: Session = Depends(get_db)):
    context: dict[str, Any] = {"tipo": body.kind}
    customer_id = body.customer_id
    channel = None
    if body.request_id:
        r = _get(db, ServiceRequest, body.request_id)
        customer_id = r.customer_id
        channel = r.customer.preferred_contact
        context.update(
            customer_name=r.customer.full_name,
            vehicle=f"{r.vehicle.make} {r.vehicle.model}" if r.vehicle else None,
            servicio=r.requested_service,
            estado=r.status,
            motivo=r.problem_description,
            fecha_solicitud=r.created_at.date().isoformat(),
            presupuesto=str(r.quote_amount) if r.quote_amount is not None else None,
        )
    elif body.conversation_id:
        c = _get(db, Conversation, body.conversation_id)
        intake = c.intake or {}
        channel = intake.get("preferred_contact")
        context.update(
            customer_name=intake.get("full_name"),
            vehicle=" ".join(str(intake[k]) for k in ("make", "model") if intake.get(k)) or None,
            motivo=intake.get("problem_description"),
            fecha_consulta=c.created_at.date().isoformat(),
        )
    elif customer_id:
        c = _get(db, Customer, customer_id)
        channel = c.preferred_contact
        context.update(customer_name=c.full_name)
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Indique una solicitud, conversación o cliente.")
    try:
        suggestion, message, source = generate_follow_up(db, body.kind, context)
    except (ProviderError, BudgetExceeded, ValueError) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "No fue posible generar el borrador.") from exc
    draft = FollowUp(
        customer_id=customer_id,
        conversation_id=body.conversation_id,
        service_request_id=body.request_id,
        kind="mensaje",
        reason=body.kind,
        channel=channel,
        message=message,
        suggestion=suggestion,
        status="borrador",
        generated_by=source,
        created_by_id=_admin_id(request),
    )
    db.add(draft)
    db.flush()
    audit(db, "admin", "followup_drafted", actor_id=_admin_id(request), entity="follow_up", entity_id=draft.id, details={"source": source})
    db.commit()
    return follow_up_out(draft)


class FollowUpPatch(BaseModel):
    message: str | None = Field(default=None, min_length=1, max_length=4000)
    channel: ContactChannel | None = None
    status: Literal["borrador", "aprobado", "enviado", "descartado"] | None = None


@router.patch("/follow-ups/{follow_up_id}")
def update_follow_up(follow_up_id: int, body: FollowUpPatch, request: Request, db: Session = Depends(get_db)):
    f = _get(db, FollowUp, follow_up_id)
    data = body.model_dump(exclude_unset=True)
    if f.status in ("enviado", "descartado") and data:
        raise HTTPException(status.HTTP_409_CONFLICT, "El seguimiento ya está cerrado.")
    if "message" in data:
        f.message = data["message"].strip()
        if f.status == "aprobado":
            f.status, f.approved_at = "borrador", None  # Un cambio exige nueva aprobación.
    if "channel" in data:
        f.channel = data["channel"]
    new_status = data.get("status")
    now = utcnow()
    if new_status == "aprobado":
        f.status, f.approved_at = "aprobado", now
    elif new_status == "enviado":
        # Solo se registra como enviado lo que el administrador aprobó y declara haber enviado.
        if f.status != "aprobado":
            raise HTTPException(status.HTTP_409_CONFLICT, "El mensaje debe aprobarse antes de registrarlo como enviado.")
        if not f.channel:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Indique el canal por el que se envió.")
        f.status, f.sent_at = "enviado", now
        if f.service_request:
            f.service_request.last_activity_at = now
    elif new_status in ("borrador", "descartado"):
        f.status = new_status
    audit(db, "admin", "followup_updated", actor_id=_admin_id(request), entity="follow_up", entity_id=f.id, details={"status": f.status})
    db.commit()
    return follow_up_out(f)


@router.get("/follow-ups/{follow_up_id}/contact")
def follow_up_contact(follow_up_id: int, db: Session = Depends(get_db)):
    """Datos de contacto para que el administrador envíe el mensaje desde su propio canal."""
    f = _get(db, FollowUp, follow_up_id)
    if f.customer:
        return {"name": f.customer.full_name, "phone": f.customer.phone, "email": f.customer.email}
    intake = (f.conversation.intake or {}) if f.conversation else {}
    return {"name": intake.get("full_name"), "phone": intake.get("phone"), "email": intake.get("email")}


# --- Auditoría -----------------------------------------------------------------------------------


@router.get("/audit")
def audit_log(db: Session = Depends(get_db), limit: int = Query(default=100, ge=1, le=500)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).all()
    return {
        "items": [
            {"id": r.id, "actor_type": r.actor_type, "actor_id": r.actor_id, "action": r.action, "entity": r.entity,
             "entity_id": r.entity_id, "details": r.details, "created_at": iso(r.created_at)}
            for r in rows
        ]
    }


@router.get("/session")
def session_info(session: AdminSession = Depends(require_admin)):
    return {"expires_at": iso(session.expires_at)}
