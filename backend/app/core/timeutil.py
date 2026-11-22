"""Time helpers. Storage is UTC; the prototype displays and reasons in Asia/Kolkata."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
WEEKDAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_utc_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def today_ist(now: datetime | None = None) -> date:
    return (now or utcnow()).astimezone(IST).date()


def ist_day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    """UTC start (inclusive) and end (exclusive) of a calendar day in IST."""
    start = datetime.combine(day, time.min, tzinfo=IST)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def ist_to_utc(day: date, at: time) -> datetime:
    return datetime.combine(day, at, tzinfo=IST).astimezone(timezone.utc)


def time_of_day(dt: datetime) -> str:
    hour = dt.astimezone(IST).hour
    if hour < 12:
        return "MORNING"
    if hour < 16:
        return "AFTERNOON"
    return "EVENING"


def resolve_date_phrase(phrase: str | None, today: date) -> date | None:
    """Resolve TODAY / TOMORROW / a weekday name / YYYY-MM-DD relative to `today`.

    Returns None for unknown phrases and for dates in the past.
    """
    if not phrase:
        return None
    p = phrase.strip().upper()
    if p == "TODAY":
        return today
    if p == "TOMORROW":
        return today + timedelta(days=1)
    if p == "DAY_AFTER_TOMORROW":
        return today + timedelta(days=2)
    if p in WEEKDAYS:
        delta = (WEEKDAYS.index(p) - today.weekday()) % 7
        return today + timedelta(days=delta or 7)
    try:
        parsed = date.fromisoformat(p)
    except ValueError:
        return None
    return parsed if parsed >= today else None
