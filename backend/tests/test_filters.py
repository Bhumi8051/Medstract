"""PubMed query building and relative publication periods."""

from datetime import date

import pytest

from app.models import ArticleType, Period
from app.services.dates import combine_period_and_range, period_start
from app.services.filters import ARTICLE_TYPE_TERMS, build_pubmed_term

# ---------- query building ----------


def test_query_without_filters_is_just_wrapped():
    assert build_pubmed_term("asthma children") == "(asthma children)"


def test_article_types_are_ored_and_anded_with_query():
    term = build_pubmed_term("asthma", [ArticleType.REVIEW, ArticleType.META_ANALYSIS])
    assert term == '(asthma) AND ("Review"[pt] OR "Meta-Analysis"[pt])'


def test_users_or_cannot_swallow_the_type_filter():
    term = build_pubmed_term("asthma OR copd", [ArticleType.RANDOMIZED_CONTROLLED_TRIAL])
    # Parentheses keep the user's OR from swallowing the filter.
    assert term == '(asthma OR copd) AND ("Randomized Controlled Trial"[pt])'


def test_repeated_filter_values_are_deduplicated():
    term = build_pubmed_term("asthma", [ArticleType.REVIEW, ArticleType.REVIEW])
    assert term == '(asthma) AND ("Review"[pt])'


def test_every_enum_value_has_a_pubmed_term():
    assert set(ARTICLE_TYPE_TERMS) == set(ArticleType)


# ---------- relative periods ----------

TODAY = date(2026, 10, 23)


def test_period_start_values():
    assert period_start(Period.ALL, TODAY) is None
    assert period_start(Period.WEEK, TODAY) == date(2026, 10, 16)
    assert period_start(Period.MONTH, TODAY) == date(2026, 9, 23)


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 3, 31), date(2026, 2, 28)),  # clamp to shorter month
        (date(2024, 3, 31), date(2024, 2, 29)),  # leap year
        (date(2026, 1, 15), date(2025, 12, 15)),  # crosses the year
    ],
)
def test_month_start_edge_cases(today, expected):
    assert period_start(Period.MONTH, today) == expected


def test_week_start_crosses_year():
    assert period_start(Period.WEEK, date(2026, 1, 3)) == date(2025, 12, 27)


def test_all_time_keeps_custom_range_unchanged():
    assert combine_period_and_range(Period.ALL, None, None, today=TODAY) == (None, None)
    custom = (date(2020, 1, 1), date(2021, 12, 31))
    assert combine_period_and_range(Period.ALL, *custom, today=TODAY) == custom


def test_week_without_custom_range_ends_today():
    assert combine_period_and_range(Period.WEEK, None, None, today=TODAY) == (date(2026, 10, 16), TODAY)


def test_period_intersects_with_custom_range():
    # Custom start inside the month -> the later start wins.
    start, end = combine_period_and_range(Period.MONTH, date(2026, 10, 1), None, today=TODAY)
    assert (start, end) == (date(2026, 10, 1), TODAY)
    # Custom range wider than the week -> the week wins.
    start, end = combine_period_and_range(Period.WEEK, date(2020, 1, 1), date(2030, 1, 1), today=TODAY)
    assert (start, end) == (date(2026, 10, 16), TODAY)


def test_non_overlapping_period_and_range_raises():
    with pytest.raises(ValueError, match="does not overlap the past week"):
        combine_period_and_range(Period.WEEK, None, date(2020, 12, 31), today=TODAY)
