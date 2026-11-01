"""Operaciones de registro compartidas por el asistente y el panel administrativo."""

import secrets
import threading
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Appointment, Customer, Service, ServiceRequest, Vehicle
from app.services.availability import overlapping_count, within_schedule
from app.services.business import get_business_settings
from app.services.intake import normalize_email, normalize_phone

# Serializa la reserva de horarios dentro del proceso para evitar dobles reservas concurrentes.
booking_lock = threading.Lock()

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class RegistryError(ValueError):
    pass


def new_request_code(db: Session) -> str:
    while True:
        code = "SAR-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        if not db.scalar(select(ServiceRequest.id).where(ServiceRequest.code == code)):
            return code


def find_customer(db: Session, email: str | None, phone: str | None) -> Customer | None:
    email_n = normalize_email(email) if email else None
    if email_n:
        customer = db.scalar(select(Customer).where(Customer.email == email_n))
        if customer:
            return customer
    phone_n = normalize_phone(phone) if phone else None
    if phone_n:
        return db.scalar(select(Customer).where(Customer.phone_normalized == phone_n).order_by(Customer.id))
    return None


def get_or_create_customer(
    db: Session, data: dict[str, Any], *, source: str, consent_at: datetime | None, consent_version: str | None
) -> tuple[Customer, bool, dict[str, Any]]:
    """Devuelve (cliente, creado, diferencias). Un cliente existente nunca se sobrescribe con datos
    aportados por un visitante; las diferencias se informan para que el taller las revise."""
    existing = find_customer(db, data.get("email"), data.get("phone"))
    if existing:
        differences = {}
        for field in ("full_name", "phone", "email"):
            declared = data.get(field)
            if declared and str(declared).strip().lower() != str(getattr(existing, field) or "").strip().lower():
                differences[field] = declared
        if not existing.preferred_contact and data.get("preferred_contact"):
            existing.preferred_contact = data["preferred_contact"]
        return existing, False, differences

    customer = Customer(
        full_name=data["full_name"],
        phone=data.get("phone"),
        phone_normalized=normalize_phone(data["phone"]) if data.get("phone") else None,
        email=normalize_email(data["email"]) if data.get("email") else None,
        preferred_contact=data.get("preferred_contact"),
        source=source,
        consent_at=consent_at,
        consent_version=consent_version,
    )
    db.add(customer)
    db.flush()
    return customer, True, {}


def get_or_create_vehicle(db: Session, customer: Customer, data: dict[str, Any]) -> tuple[Vehicle, bool, dict[str, Any]]:
    notes: dict[str, Any] = {}
    plate = data.get("plate")
    vehicle = None
    if plate:
        owner_vehicle = db.scalar(select(Vehicle).where(Vehicle.plate == plate))
        if owner_vehicle and owner_vehicle.customer_id == customer.id:
            vehicle = owner_vehicle
        elif owner_vehicle:
            # La patente ya pertenece a otro cliente: no se vincula automáticamente.
            notes["patente_registrada_en_otro_cliente"] = plate
            plate = None
    if vehicle is None:
        vehicle = db.scalar(
            select(Vehicle).where(
                Vehicle.customer_id == customer.id,
                func.lower(Vehicle.make) == data["make"].lower(),
                func.lower(Vehicle.model) == data["model"].lower(),
                Vehicle.year == data.get("year"),
            )
        )
    if vehicle:
        if data.get("mileage_km") and (vehicle.mileage_km or 0) < data["mileage_km"]:
            vehicle.mileage_km = data["mileage_km"]
        for field in ("version", "vin"):
            if data.get(field) and not getattr(vehicle, field):
                setattr(vehicle, field, data[field])
        if plate and not vehicle.plate:
            vehicle.plate = plate
        return vehicle, False, notes

    vehicle = Vehicle(
        customer_id=customer.id,
        make=data["make"],
        model=data["model"],
        year=data.get("year"),
        version=data.get("version"),
        mileage_km=data.get("mileage_km"),
        plate=plate,
        vin=data.get("vin"),
    )
    db.add(vehicle)
    db.flush()
    return vehicle, True, notes


def create_service_request(
    db: Session,
    *,
    customer: Customer,
    vehicle: Vehicle | None,
    data: dict[str, Any],
    source: str,
    conversation_id: int | None = None,
    ai_summary: str | None = None,
    extra: dict[str, Any] | None = None,
) -> ServiceRequest:
    service = None
    if data.get("service_slug"):
        service = db.scalar(select(Service).where(Service.slug == data["service_slug"]))
    request = ServiceRequest(
        code=new_request_code(db),
        customer_id=customer.id,
        vehicle_id=vehicle.id if vehicle else None,
        service_id=service.id if service else None,
        conversation_id=conversation_id,
        source=source,
        requested_service=service.name if service else data.get("requested_service"),
        problem_description=data.get("problem_description"),
        symptoms=data.get("symptoms"),
        onset=data.get("onset"),
        frequency=data.get("frequency"),
        customer_availability=data.get("availability"),
        preferred_date=data.get("preferred_date"),
        additional_notes=data.get("additional_notes"),
        extra_data=extra or {},
        ai_summary=ai_summary,
        status="nueva",
        last_activity_at=utcnow(),
    )
    db.add(request)
    db.flush()
    return request


def book_appointment(
    db: Session,
    *,
    customer_id: int,
    start: datetime,
    end: datetime | None = None,
    vehicle_id: int | None = None,
    service_request_id: int | None = None,
    status: str = "solicitado",
    created_by: str = "asistente",
    notes: str | None = None,
    allow_outside_schedule: bool = False,
    exclude_id: int | None = None,
) -> Appointment:
    """Crea un turno solo si el horario está libre según la capacidad configurada."""
    settings = get_business_settings(db)
    end = end or start + timedelta(minutes=settings.slot_minutes)
    if end <= start:
        raise RegistryError("El horario de finalización debe ser posterior al de inicio.")
    with booking_lock:
        if not allow_outside_schedule and not within_schedule(settings, start, end):
            raise RegistryError("El horario está fuera de la agenda de atención del taller.")
        if overlapping_count(db, start, end, exclude_id) >= settings.bays:
            raise RegistryError("El horario ya no está disponible.")
        appointment = Appointment(
            customer_id=customer_id,
            vehicle_id=vehicle_id,
            service_request_id=service_request_id,
            start_at=start,
            end_at=end,
            status=status,
            created_by=created_by,
            notes=notes,
        )
        db.add(appointment)
        db.flush()
        return appointment

