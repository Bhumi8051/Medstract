"""Step D stage 1: next-run calculation (pure functions, no database).

2026 US daylight-saving changes: spring forward Sun 8 March (02:00 -> 03:00),
fall back Sun 1 November (02:00 -> 01:00).
"""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from app.models import SubscriptionFrequency as F
from app.services.schedule import next_run_after, to_python_weekday

NY = ZoneInfo("America/New_York")


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def run(frequency=F.DAILY, *, at=time(9, 0), tz="America/New_York", weekday=None, month_day=None, after):
    return next_run_after(
        frequency=frequency, weekday=weekday, month_day=month_day, delivery_time=at, time_zone=tz, after=after
    )


# ---------------------------------------------------------------- basics


def test_daily_later_today():
    # 08:00 EDT -> 09:00 EDT the same day
    assert run(after=utc(2026, 10, 25, 12, 0)) == utc(2026, 10, 25, 13, 0)


def test_result_is_strictly_after_the_given_moment():
    assert run(after=utc(2026, 10, 25, 13, 0)) == utc(2026, 10, 26, 13, 0)
    assert run(after=utc(2026, 10, 25, 12, 59, 59)) == utc(2026, 10, 25, 13, 0)


def test_results_are_utc():
    assert run(after=utc(2026, 10, 25, 12, 0)).tzinfo is UTC


@pytest.mark.parametrize("app_weekday", range(7))
def test_weekday_numbering_is_sunday_zero(app_weekday):
    # Saturday 24 Oct 2026 -> Sunday 25 Oct is app weekday 0, Monday 26 is 1, ...
    result = run(F.WEEKLY, weekday=app_weekday, at=time(12, 0), tz="UTC", after=utc(2026, 10, 24, 13, 0))
    assert result == utc(2026, 10, 25 + app_weekday, 12, 0)
    assert result.strftime("%A") == ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][app_weekday]


def test_python_weekday_mapping():
    assert [to_python_weekday(d) for d in range(7)] == [6, 0, 1, 2, 3, 4, 5]


def test_weekly_from_the_same_weekday_after_the_time_is_next_week():
    assert run(F.WEEKLY, weekday=0, at=time(9, 0), tz="UTC", after=utc(2026, 10, 25, 10, 0)) == utc(2026, 11, 1, 9, 0)


@pytest.mark.parametrize(
    ("month_day", "after", "expected"),
    [
        (15, utc(2026, 10, 20, 0, 0), utc(2026, 11, 15, 9, 0)),
        (28, utc(2027, 2, 1, 0, 0), utc(2027, 2, 28, 9, 0)),  # February always has day 28
        (1, utc(2026, 12, 31, 12, 0), utc(2027, 1, 1, 9, 0)),  # across a year boundary
        (5, utc(2026, 10, 5, 8, 59), utc(2026, 10, 5, 9, 0)),  # later the same day
    ],
)
def test_monthly(month_day, after, expected):
    assert run(F.MONTHLY, month_day=month_day, tz="UTC", after=after) == expected


# ---------------------------------------------------------------- time zones


def test_midnight_on_the_owners_subscription():
    # Weekly, Sunday 00:00 America/New_York. Saturday 23:58 EDT -> Sunday 00:00 EDT.
    assert run(F.WEEKLY, weekday=0, at=time(0, 0), after=utc(2026, 10, 25, 3, 58)) == utc(2026, 10, 25, 4, 0)


def test_half_hour_offset_kolkata():
    # 07:00 IST (+05:30) = 01:30 UTC
    assert run(at=time(7, 0), tz="Asia/Kolkata", after=utc(2026, 10, 25, 0, 0)) == utc(2026, 10, 25, 1, 30)


def test_quarter_hour_offset_and_date_line_chatham():
    # Chatham Islands in October: +13:45. Local midnight of 26 Oct = 25 Oct 10:15 UTC.
    assert run(at=time(0, 0), tz="Pacific/Chatham", after=utc(2026, 10, 25, 0, 0)) == utc(2026, 10, 25, 10, 15)


def test_negative_offset_where_the_utc_date_is_ahead():
    # 00:00 UTC on 25 Oct is 17:00 PDT on 24 Oct; that evening's 23:30 PDT (-7)
    # is 06:30 UTC on the 25th.
    assert run(at=time(23, 30), tz="America/Los_Angeles", after=utc(2026, 10, 25, 0, 0)) == utc(2026, 10, 25, 6, 30)


# ---------------------------------------------------------------- daylight saving


def test_spring_forward_missing_time_moves_forward_by_the_gap():
    # 02:30 doesn't exist on 8 March: it is sent at 03:30 EDT (07:30 UTC), once.
    first = run(at=time(2, 30), after=utc(2026, 3, 8, 5, 0))  # after = 00:00 EST
    assert first == utc(2026, 3, 8, 7, 30)
    assert first.astimezone(NY).strftime("%H:%M %Z") == "03:30 EDT"
    # The following day is normal again: 02:30 EDT = 06:30 UTC.
    assert run(at=time(2, 30), after=first) == utc(2026, 3, 9, 6, 30)


def test_fall_back_repeated_time_runs_once_at_the_first_occurrence():
    # 01:30 happens twice on 1 November; use the first (EDT, 05:30 UTC).
    first = run(at=time(1, 30), after=utc(2026, 11, 1, 4, 0))
    assert first == utc(2026, 11, 1, 5, 30)
    assert first.astimezone(NY).strftime("%H:%M %Z") == "01:30 EDT"
    # The second 01:30 (EST, 06:30 UTC) must NOT produce another run that day.
    second = run(at=time(1, 30), after=first)
    assert second == utc(2026, 11, 2, 6, 30)
    assert second.astimezone(NY).strftime("%Y-%m-%d %H:%M %Z") == "2026-11-02 01:30 EST"


def test_weekly_midnight_across_the_fall_back_change():
    # Sunday 00:00 is before the 02:00 change, so 1 Nov is still EDT (04:00 UTC);
    # the next Sunday is EST (05:00 UTC). The wall-clock time stays 00:00.
    nov1 = run(F.WEEKLY, weekday=0, at=time(0, 0), after=utc(2026, 10, 25, 4, 0))
    assert nov1 == utc(2026, 11, 1, 4, 0)
    nov8 = run(F.WEEKLY, weekday=0, at=time(0, 0), after=nov1)
    assert nov8 == utc(2026, 11, 8, 5, 0)


def test_a_year_of_daily_runs_keeps_the_wall_clock_time_and_never_repeats():
    runs, moment = [], utc(2026, 1, 1, 0, 0)
    for _ in range(365):
        moment = run(at=time(9, 0), after=moment)
        runs.append(moment)
    local = [r.astimezone(NY) for r in runs]
    assert all(t.strftime("%H:%M") == "09:00" for t in local)
    assert len({t.date() for t in local}) == 365  # one per day: no gaps, no doubles
    assert all(b > a for a, b in zip(runs, runs[1:]))


def test_a_year_of_weekly_runs_through_both_changes():
    runs, moment = [], utc(2026, 1, 1, 0, 0)
    while moment < utc(2027, 1, 1, 0, 0):
        moment = run(F.WEEKLY, weekday=0, at=time(2, 30), after=moment)
        runs.append(moment)
    local = [r.astimezone(NY) for r in runs[:-1]]
    assert all(t.strftime("%A") == "Sunday" for t in local)
    gaps = {b - a for a, b in zip(runs, runs[1:])}
    # Exactly a week apart, except across the two changes (one hour shorter/longer)
    # and the missing-02:30 Sunday (sent at 03:30).
    assert gaps <= {timedelta(days=7), timedelta(days=7, hours=-1), timedelta(days=7, hours=1)}


# ---------------------------------------------------------------- invalid input


def test_naive_datetimes_are_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        run(after=datetime(2026, 10, 25, 12, 0))


@pytest.mark.parametrize(("frequency", "fields"), [(F.WEEKLY, {}), (F.MONTHLY, {})])
def test_missing_day_is_rejected(frequency, fields):
    with pytest.raises(ValueError):
        run(frequency, after=utc(2026, 10, 25), **fields)


def test_unknown_time_zone_is_rejected():
    with pytest.raises(ZoneInfoNotFoundError):
        run(tz="Mars/Olympus_Mons", after=utc(2026, 10, 25))
