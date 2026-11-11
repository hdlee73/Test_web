from __future__ import annotations

from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9), "KST")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def from_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def kst_midnight(now: datetime, days_back: int = 0) -> datetime:
    """now 기준 KST 자정(days_back 일 전)을 UTC datetime 으로."""
    local = now.astimezone(KST)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_back)
    return midnight.astimezone(timezone.utc)
