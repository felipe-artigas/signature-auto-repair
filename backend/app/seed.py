"""Datos iniciales: catálogo de servicios y configuración provisional del negocio. Idempotente."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Service
from app.services.business import get_business_settings

SERVICES = [
    ("diagnostico-computarizado", "Diagnóstico computarizado", "Diagnóstico",
     "Lectura de módulos electrónicos, análisis de códigos de falla y parámetros en tiempo real, con informe para el cliente."),
    ("mecanica-integral", "Mecánica integral", "Mecánica",
     "Intervenciones sobre motor, distribución, refrigeración y componentes mecánicos con procedimientos del fabricante."),
    ("mantenimiento-preventivo", "Mantenimiento preventivo", "Mantenimiento",
     "Servicios periódicos según plan del fabricante: fluidos, filtros, controles y registro del historial del vehículo."),
    ("sistemas-de-frenos", "Sistemas de frenos", "Seguridad",
     "Control y reemplazo de pastillas, discos, líquido y componentes, incluidos sistemas de alto rendimiento."),
    ("suspension-y-direccion", "Suspensión y dirección", "Chasis",
     "Revisión de amortiguación, tren delantero y trasero, suspensiones neumáticas y adaptativas, y geometría."),
    ("electricidad-y-electronica", "Electricidad y electrónica", "Electrónica",
     "Sistemas de carga, iluminación, confort, sensores y asistencias a la conducción."),
    ("transmision", "Transmisión", "Mecánica",
     "Cajas automáticas, de doble embrague y manuales: control, mantenimiento de fluidos y adaptaciones."),
    ("climatizacion", "Climatización", "Confort",
     "Control de carga, fugas y rendimiento del aire acondicionado y la calefacción."),
    ("inspeccion-general", "Inspección general", "Inspección",
     "Revisión integral del estado del vehículo antes de un viaje, una compra o un cambio de estación."),
]


def seed(db: Session) -> None:
    get_business_settings(db)
    existing = set(db.scalars(select(Service.slug)).all())
    for order, (slug, name, category, description) in enumerate(SERVICES):
        if slug not in existing:
            db.add(Service(slug=slug, name=name, category=category, description=description, sort_order=order * 10))
    db.commit()
