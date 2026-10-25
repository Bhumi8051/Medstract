"""When is a subscription's next digest due? (Step D, stage 1: calculation only.)

Subscriptions store a wall-clock schedule in the user's time zone: "weekly on
Sunday at 00:00 America/New_York". This module turns that into the next UTC
instant strictly after a given moment. Nothing here sends anything.

Daylight-saving rules (PEP 495, fold=0):
  - A local time that doesn't exist (spring forward, e.g. 02:30 on the US
    change day) is shifted forward by the length of the gap: 02:30 -> 03:30.
  - A local time that happens twice (fall back, e.g. 01:30) is used once,
    at its FIRST occurrence (daylight time).
Monthly days are limited to 1-28, so every month has the chosen day.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models import SubscriptionFrequency

# The app numbers weekdays 0 = Sunday ... 6 = Saturday; Python's date.weekday()
# uses 0 = Monday ... 6 = Sunday.
def to_python_weekday(app_weekday: int) -> int:
    return (app_weekday - 1) % 7


def local_to_utc(day: date, at: time, zone: ZoneInfo) -> datetime:
    """The UTC instant for a wall-clock time, applying the DST rules above."""
    return datetime.combine(day, at, tzinfo=zone).replace(fold=0).astimezone(UTC)


def _matches(day: date, frequency: SubscriptionFrequency, weekday: int | None, month_day: int | None) -> bool:
    if frequency is SubscriptionFrequency.DAILY:
        return True
    if frequency is SubscriptionFrequency.WEEKLY:
        return weekday is not None and day.weekday() == to_python_weekday(weekday)
    return month_day is not None and day.day == month_day


def next_run_after(
    *,
    frequency: SubscriptionFrequency,
    weekday: int | None,
    month_day: int | None,
    delivery_time: time,
    time_zone: str,
    after: datetime,
) -> datetime:
    """First scheduled delivery strictly after `after` (an aware datetime), in UTC."""
    if after.tzinfo is None:
        raise ValueError("`after` must be timezone-aware")
    if frequency is SubscriptionFrequency.WEEKLY and weekday is None:
        raise ValueError("weekly schedules need a weekday")
    if frequency is SubscriptionFrequency.MONTHLY and month_day is None:
        raise ValueError("monthly schedules need a month_day")

    zone = ZoneInfo(time_zone)
    # Start one day early: near midnight, the local date of `after` can lag the
    # date on which the next run falls (and DST shifts can move it by an hour).
    day = after.astimezone(zone).date() - timedelta(days=1)
    for _ in range(64):  # a monthly match is never more than ~32 days away
        if _matches(day, frequency, weekday, month_day):
            candidate = local_to_utc(day, delivery_time, zone)
            if candidate > after:
                return candidate
        day += timedelta(days=1)
    raise RuntimeError("no scheduled time found")  # unreachable for valid schedules
