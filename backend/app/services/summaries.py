"""Textos generados a partir de datos reales, con IA cuando está habilitada y con plantillas en otro caso."""

from typing import Any

FREQ = {"constante": "constante", "intermitente": "intermitente", "no_sabe": "frecuencia no informada"}


def vehicle_label(data: dict[str, Any]) -> str:
    parts = [data.get("make"), data.get("model"), data.get("version"), str(data["year"]) if data.get("year") else None]
    return " ".join(p for p in parts if p)


def fallback_request_summary(data: dict[str, Any]) -> str:
    """Resumen estructurado sin IA. Solo reordena lo declarado por el cliente; no interpreta ni diagnostica."""
    lines = [f"Vehículo: {vehicle_label(data)}"]
    if data.get("mileage_km"):
        lines[0] += f", {data['mileage_km']:,} km".replace(",", ".")
    if data.get("problem_description"):
        lines.append(f"Motivo declarado por el cliente: {data['problem_description']}")
    details = []
    if data.get("symptoms"):
        details.append(f"síntomas: {data['symptoms']}")
    if data.get("onset"):
        details.append(f"inicio: {data['onset']}")
    if data.get("frequency"):
        details.append(f"frecuencia: {FREQ.get(data['frequency'], data['frequency'])}")
    if details:
        lines.append("Detalle declarado: " + "; ".join(details) + ".")
    if data.get("availability") or data.get("preferred_date"):
        lines.append(
            "Disponibilidad: " + ", ".join(v for v in (data.get("availability"), data.get("preferred_date")) if v)
        )
    lines.append("Sin diagnóstico: requiere evaluación profesional del vehículo.")
    return "\n".join(lines)
