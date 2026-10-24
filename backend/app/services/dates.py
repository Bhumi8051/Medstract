"""Date parsing and publication-date filtering.

Dates may be partial ('2021' or '2021-03'). A partial date is treated as the
whole period it covers, so '2021' means 2021-01-01 through 2021-12-31.
"""

import calendar
import re
from datetime import date, timedelta

from app.models import Paper, Period

_PARTIAL_DATE_RE = re.compile(r"^(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?$")
_MIN_YEAR = 1000  # keeps strftime and NCBI date formats well-behaved


def period_bounds(year: int, month: int | None = None, day: int | None = None) -> tuple[date, date]:
    """First and last day covered by a (possibly partial) date. Raises ValueError if invalid."""
    if year < _MIN_YEAR:
        raise ValueError(f"Year {year} is out of range.")
    if month is None:
        return date(year, 1, 1), date(year, 12, 31)
    if not 1 <= month <= 12:
        raise ValueError(f"Month {month} is out of range.")
    if day is None:
        return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    exact = date(year, month, day)  # raises ValueError for e.g. Feb 30
    return exact, exact


def _parse_partial(value: str) -> tuple[date, date]:
    match = _PARTIAL_DATE_RE.match(value.strip())
    if not match:
        raise ValueError(f"Invalid date '{value}'. Use YYYY, YYYY-MM, or YYYY-MM-DD.")
    year, month, day = (int(g) if g else None for g in match.groups())
    try:
        return period_bounds(year, month, day)  # type: ignore[arg-type]
    except ValueError as exc:
        raise ValueError(f"Invalid date '{value}': {exc}") from exc


def parse_date_bound(value: str, *, is_end: bool) -> date:
    """Parse a user-supplied filter date.

    Partial start dates expand to the start of the period ('2020' -> 2020-01-01);
    partial end dates expand to the end ('2020-02' -> 2020-02-29).
    """
    earliest, latest = _parse_partial(value)
    return latest if is_end else earliest


def iso_bounds(iso: str | None) -> tuple[date, date] | None:
    """Period covered by a paper's partial ISO date, or None if missing or unparseable."""
    if not iso:
        return None
    try:
        return _parse_partial(iso)
    except ValueError:
        return None


def paper_matches_date_range(
    paper: Paper,
    start: date | None,
    end: date | None,
    *,
    include_undated: bool = False,
) -> bool:
    """True if any known date of the paper (print or electronic) overlaps [start, end]."""
    if start is None and end is None:
        return True
    periods = [
        bounds
        for bounds in (iso_bounds(paper.publication_date_iso), iso_bounds(paper.electronic_date_iso))
        if bounds is not None
    ]
    if not periods:
        return include_undated
    lower = start or date.min
    upper = end or date.max
    return any(first <= upper and last >= lower for first, last in periods)


def has_known_date(paper: Paper) -> bool:
    return bool(iso_bounds(paper.publication_date_iso) or iso_bounds(paper.electronic_date_iso))


def _one_month_before(day: date) -> date:
    """Same day last month, clamped to that month's length (Mar 31 -> Feb 28/29)."""
    year, month = (day.year, day.month - 1) if day.month > 1 else (day.year - 1, 12)
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def period_start(period: Period, today: date) -> date | None:
    """First day of a relative period ending today, or None for 'all'."""
    if period is Period.WEEK:
        return today - timedelta(days=7)
    if period is Period.MONTH:
        return _one_month_before(today)
    return None


def combine_period_and_range(
    period: Period,
    start: date | None,
    end: date | None,
    *,
    today: date,
) -> tuple[date | None, date | None]:
    """Intersect a relative period (e.g. past week) with an optional custom range.

    'all' leaves the custom range untouched. Raises ValueError if the two
    don't overlap, e.g. period=week with end_date in 2020.
    """
    since = period_start(period, today)
    if since is None:
        return start, end

    effective_start = max(start, since) if start else since
    effective_end = min(end, today) if end else today
    if effective_start > effective_end:
        raise ValueError(
            f"The selected date range does not overlap the past {period.value} "
            f"({since.isoformat()} to {today.isoformat()})."
        )
    return effective_start, effective_end


def to_ncbi_date(value: date) -> str:
    """Format for ESearch mindate/maxdate parameters."""
    return value.strftime("%Y/%m/%d")
