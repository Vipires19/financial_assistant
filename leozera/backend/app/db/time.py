from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def local_today() -> date:
    from app.core.config import get_settings

    name = get_settings().app_timezone
    try:
        zone = ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name != "America/Sao_Paulo":
            raise
        zone = timezone(timedelta(hours=-3))
    return datetime.now(zone).date()
