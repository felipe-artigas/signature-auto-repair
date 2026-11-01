"""Validación y normalización de los datos que el asistente recopila durante la conversación."""

import re
from typing import Any

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Service

INTAKE_FIELDS: dict[str, str] = {
    "full_name": "Nombre y apellido",
    "phone": "Teléfono",
    "email": "Correo electrónico",
    "preferred_contact": "Medio de contacto preferido",
    "make": "Marca",
    "model": "Modelo",
    "year": "Año",
    "version": "Versión o motorización",
    "mileage_km": "Kilometraje aproximado",
    "plate": "Patente",
    "vin": "VIN",
    "service_slug": "Servicio solicitado",
    "problem_description": "Descripción del problema",
    "symptoms": "Síntomas observados",
    "onset": "Cuándo comenzó",
    "frequency": "Frecuencia",
    "availability": "Disponibilidad del cliente",
    "preferred_date": "Fecha y horario preferidos",
    "additional_notes": "Observaciones adicionales",
}

REQUIRED_FIELDS = ("full_name", "phone", "email", "make", "model", "year")
# Al menos uno de estos campos identifica el motivo de la consulta.
REASON_FIELDS = ("service_slug", "problem_description")
# Campos recomendados que el asistente debe intentar obtener sin volverlos obligatorios.
RECOMMENDED_FIELDS = ("mileage_km", "preferred_contact", "availability")

FREQUENCY_VALUES = {"constante", "intermitente", "no_sabe"}
CONTACT_VALUES = {"telefono", "whatsapp", "email"}

_TEXT_LIMITS = {
    "full_name": 120,
    "make": 60,
    "model": 80,
    "version": 80,
    "problem_description": 1500,
    "symptoms": 1000,
    "onset": 200,
    "availability": 300,
    "preferred_date": 120,
    "additional_notes": 1000,
}

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = _CONTROL_CHARS.sub("", str(value)).strip()
    text = re.sub(r"[ \t]+", " ", text)
    return text[:limit] or None


def normalize_phone(value: str) -> str | None:
    digits = re.sub(r"\D", "", value)
    return digits if 8 <= len(digits) <= 15 else None


def normalize_email(value: str) -> str | None:
    try:
        return validate_email(value.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        return None


def normalize_plate(value: str) -> str | None:
    plate = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    return plate if 5 <= len(plate) <= 10 else None


def normalize_vin(value: str) -> str | None:
    vin = re.sub(r"\s", "", value).upper()
    return vin if re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", vin) else None


def validate_update(db: Session, raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Devuelve (campos válidos normalizados, errores por campo). Los valores nulos se ignoran."""
    clean: dict[str, Any] = {}
    errors: dict[str, str] = {}
    current_year = utcnow().year

    for key, value in raw.items():
        if key not in INTAKE_FIELDS or value is None or (isinstance(value, str) and not value.strip()):
            continue
        if key in _TEXT_LIMITS:
            text = clean_text(value, _TEXT_LIMITS[key])
            if text:
                clean[key] = text
        elif key == "phone":
            phone = normalize_phone(str(value))
            if phone:
                clean[key] = clean_text(value, 40)
            else:
                errors[key] = "El teléfono debe tener entre 8 y 15 dígitos."
        elif key == "email":
            email = normalize_email(str(value))
            if email:
                clean[key] = email
            else:
                errors[key] = "El correo electrónico no tiene un formato válido."
        elif key == "year":
            try:
                year = int(str(value).strip())
            except ValueError:
                year = 0
            if 1950 <= year <= current_year + 1:
                clean[key] = year
            else:
                errors[key] = f"El año debe estar entre 1950 y {current_year + 1}."
        elif key == "mileage_km":
            try:
                km = int(re.sub(r"[^\d]", "", str(value)) or "-1")
            except ValueError:
                km = -1
            if 0 <= km <= 2_000_000:
                clean[key] = km
            else:
                errors[key] = "El kilometraje debe ser un número entre 0 y 2.000.000."
        elif key == "plate":
            plate = normalize_plate(str(value))
            if plate:
                clean[key] = plate
            else:
                errors[key] = "La patente no tiene un formato válido."
        elif key == "vin":
            vin = normalize_vin(str(value))
            if vin:
                clean[key] = vin
            else:
                errors[key] = "El VIN debe tener 17 caracteres alfanuméricos (sin I, O ni Q)."
        elif key == "frequency":
            freq = str(value).strip().lower()
            if freq in FREQUENCY_VALUES:
                clean[key] = freq
            else:
                errors[key] = "La frecuencia debe ser constante, intermitente o no_sabe."
        elif key == "preferred_contact":
            channel = str(value).strip().lower().replace("é", "e")
            if channel in CONTACT_VALUES:
                clean[key] = channel
            else:
                errors[key] = "El medio de contacto debe ser telefono, whatsapp o email."
        elif key == "service_slug":
            slug = str(value).strip().lower()
            exists = db.scalar(select(Service.id).where(Service.slug == slug, Service.is_active.is_(True)))
            if exists:
                clean[key] = slug
            else:
                errors[key] = "El servicio indicado no existe. Consulte get_available_services."
    return clean, errors


def missing_fields(intake: dict[str, Any]) -> list[str]:
    missing = [f for f in REQUIRED_FIELDS if not intake.get(f)]
    if not any(intake.get(f) for f in REASON_FIELDS):
        missing.append("problem_description")
    return missing


def missing_recommended(intake: dict[str, Any]) -> list[str]:
    return [f for f in RECOMMENDED_FIELDS if not intake.get(f)]


def summary_lines(db: Session, intake: dict[str, Any]) -> list[dict[str, str]]:
    """Resumen legible, construido por el backend a partir de los datos validados."""
    lines = []
    for key, label in INTAKE_FIELDS.items():
        value = intake.get(key)
        if value in (None, ""):
            continue
        if key == "service_slug":
            service = db.scalar(select(Service).where(Service.slug == value))
            value = service.name if service else value
        elif key == "mileage_km":
            value = f"{int(value):,} km".replace(",", ".")
        elif key == "frequency":
            value = {"constante": "Constante", "intermitente": "Intermitente", "no_sabe": "No lo sabe"}[value]
        elif key == "preferred_contact":
            value = {"telefono": "Teléfono", "whatsapp": "WhatsApp", "email": "Correo electrónico"}[value]
        lines.append({"field": key, "label": label, "value": str(value)})
    return lines
