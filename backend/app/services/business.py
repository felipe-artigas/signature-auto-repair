from sqlalchemy.orm import Session

from app.models import BusinessSettings

PLACEHOLDER_CONTACT = {
    "phone": "+54 11 0000-0000",
    "whatsapp": "+54 9 11 0000-0000",
    "email": "contacto@ejemplo.com",
    "address": "Dirección a confirmar",
    "city": "Ciudad a confirmar",
    "hours_text": "Lunes a viernes de 9:00 a 18:00 · Sábados de 9:00 a 13:00",
    "maps_url": "",
    "instagram": "",
    # Mientras sea verdadero, la web indica que los datos son provisionales.
    "is_placeholder": True,
}

DEFAULT_SCHEDULE = {
    "0": [["09:00", "18:00"]],
    "1": [["09:00", "18:00"]],
    "2": [["09:00", "18:00"]],
    "3": [["09:00", "18:00"]],
    "4": [["09:00", "18:00"]],
    "5": [["09:00", "13:00"]],
    "6": [],
}


def get_business_settings(db: Session) -> BusinessSettings:
    settings = db.get(BusinessSettings, 1)
    if settings is None:
        settings = BusinessSettings(
            id=1,
            contact=dict(PLACEHOLDER_CONTACT),
            weekly_schedule=dict(DEFAULT_SCHEDULE),
            closed_dates=[],
        )
        db.add(settings)
        db.commit()
    return settings
