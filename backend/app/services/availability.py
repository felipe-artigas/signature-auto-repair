"""Cálculo de disponibilidad real a partir de la agenda configurada y los turnos existentes."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import APPOINTMENT_ACTIVE_STATUSES, Appointment, BusinessSettings


@dataclass(frozen=True)
class Slot:
    start: datetime  # UTC naive
    end: datetime  # UTC naive


def to_local(dt_utc: datetime, tz: str) -> datetime:
    return dt_utc.replace(tzinfo=UTC).astimezone(ZoneInfo(tz))


def to_utc(dt_local: datetime, tz: str) -> datetime:
    if dt_local.tzinfo is None:
        dt_local = dt_local.replace(tzinfo=ZoneInfo(tz))
    return dt_local.astimezone(UTC).replace(tzinfo=None)


def _parse_hhmm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def overlapping_count(db: Session, start: datetime, end: datetime, exclude_id: int | None = None) -> int:
    query = select(Appointment.id).where(
        Appointment.status.in_(APPOINTMENT_ACTIVE_STATUSES),
        Appointment.start_at < end,
        Appointment.end_at > start,
    )
    if exclude_id is not None:
        query = query.where(Appointment.id != exclude_id)
    return len(db.scalars(query).all())


def within_schedule(settings: BusinessSettings, start: datetime, end: datetime) -> bool:
    """Indica si el intervalo (UTC) cae completo dentro de un bloque de atención del día."""
    local_start = to_local(start, settings.timezone)
    local_end = to_local(end, settings.timezone)
    if local_start.date() != local_end.date() or local_start.date().isoformat() in settings.closed_dates:
        return False
    for block_start, block_end in settings.weekly_schedule.get(str(local_start.weekday()), []):
        if _parse_hhmm(block_start) <= local_start.time() and local_end.time() <= _parse_hhmm(block_end):
            return True
    return False


def is_slot_available(
    db: Session, settings: BusinessSettings, start: datetime, end: datetime, exclude_id: int | None = None
) -> bool:
    return within_schedule(settings, start, end) and overlapping_count(db, start, end, exclude_id) < settings.bays


def free_slots(
    db: Session,
    settings: BusinessSettings,
    date_from: date,
    days: int,
    *,
    limit: int = 12,
    enforce_notice: bool = True,
) -> list[Slot]:
    tz = settings.timezone
    now = utcnow()
    earliest = now + timedelta(hours=settings.min_notice_hours) if enforce_notice else now
    horizon_end = now + timedelta(days=settings.booking_horizon_days)
    step = timedelta(minutes=settings.slot_minutes)

    first_day = max(date_from, to_local(now, tz).date())
    window_start = to_utc(datetime.combine(first_day, time.min), tz)
    window_end = to_utc(datetime.combine(first_day + timedelta(days=days), time.min), tz)
    busy = db.execute(
        select(Appointment.start_at, Appointment.end_at).where(
            Appointment.status.in_(APPOINTMENT_ACTIVE_STATUSES),
            Appointment.start_at < window_end,
            Appointment.end_at > window_start,
        )
    ).all()

    slots: list[Slot] = []
    for offset in range(max(0, min(days, 31))):
        day = first_day + timedelta(days=offset)
        if day.isoformat() in settings.closed_dates:
            continue
        for block_start, block_end in settings.weekly_schedule.get(str(day.weekday()), []):
            cursor = datetime.combine(day, _parse_hhmm(block_start))
            block_limit = datetime.combine(day, _parse_hhmm(block_end))
            while cursor + step <= block_limit:
                start_utc, end_utc = to_utc(cursor, tz), to_utc(cursor + step, tz)
                cursor += step
                if start_utc < earliest or start_utc > horizon_end:
                    continue
                taken = sum(1 for b_start, b_end in busy if b_start < end_utc and b_end > start_utc)
                if taken < settings.bays:
                    slots.append(Slot(start_utc, end_utc))
                    if len(slots) >= limit:
                        return slots
    return slots
