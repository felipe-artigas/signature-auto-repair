from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Service
from app.services.business import get_business_settings

router = APIRouter(prefix="/api", tags=["público"])

DAY_NAMES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/public/site")
def site(db: Session = Depends(get_db)):
    settings = get_business_settings(db)
    services = db.scalars(
        select(Service).where(Service.is_active.is_(True)).order_by(Service.sort_order, Service.name)
    ).all()
    contact = {k: v for k, v in settings.contact.items()}
    schedule = [
        {"day": DAY_NAMES[int(day)], "blocks": blocks}
        for day, blocks in sorted(settings.weekly_schedule.items(), key=lambda kv: int(kv[0]))
    ]
    return {
        "business_name": settings.business_name,
        "contact": contact,
        "schedule": schedule,
        "assistant_mode": "openai" if get_settings().ai_enabled else "mock",
        "services": [
            {
                "slug": s.slug,
                "name": s.name,
                "description": s.description,
                "category": s.category,
                "price_info": s.price_info,
            }
            for s in services
        ],
    }
