from datetime import date

import pytest

from app.services.dates import iso_bounds, paper_matches_date_range, parse_date_bound
from tests.conftest import make_paper


@pytest.mark.parametrize(
    ("value", "is_end", "expected"),
    [
        ("2020", False, date(2020, 1, 1)),
        ("2020", True, date(2020, 12, 31)),
        ("2024-02", True, date(2024, 2, 29)),  # leap year
        ("2023-02", True, date(2023, 2, 28)),
        ("2021-3", False, date(2021, 3, 1)),
        ("2021-03-15", False, date(2021, 3, 15)),
        (" 2021-03-15 ", True, date(2021, 3, 15)),
    ],
)
def test_parse_date_bound_expands_partial_dates(value, is_end, expected):
    assert parse_date_bound(value, is_end=is_end) == expected


@pytest.mark.parametrize(
    "value", ["", "20", "20201", "abcd", "2020/01/01", "2020-13", "2021-02-30", "0999", "2020-01-01T00:00"]
)
def test_parse_date_bound_rejects_invalid_input(value):
    with pytest.raises(ValueError):
        parse_date_bound(value, is_end=False)


def test_iso_bounds_handles_missing_and_bad_values():
    assert iso_bounds(None) is None
    assert iso_bounds("not-a-date") is None
    assert iso_bounds("2022-06") == (date(2022, 6, 1), date(2022, 6, 30))


def test_no_filter_keeps_everything_including_undated():
    assert paper_matches_date_range(make_paper(), None, None)


def test_full_date_inside_and_outside_range():
    paper = make_paper(publication_date_iso="2021-05-10")
    assert paper_matches_date_range(paper, date(2021, 1, 1), date(2021, 12, 31))
    assert not paper_matches_date_range(paper, date(2022, 1, 1), None)
    assert not paper_matches_date_range(paper, None, date(2021, 5, 9))


def test_partial_paper_date_matches_if_period_overlaps():
    year_only = make_paper(publication_date_iso="2020")
    # The year 2020 overlaps a range starting mid-2020.
    assert paper_matches_date_range(year_only, date(2020, 6, 1), None)
    month_only = make_paper(publication_date_iso="2019-12")
    assert not paper_matches_date_range(month_only, date(2020, 1, 1), None)
    assert paper_matches_date_range(month_only, None, date(2019, 12, 1))


def test_electronic_date_counts_when_print_date_is_outside_range():
    paper = make_paper(publication_date_iso="2024-01", electronic_date_iso="2023-12-20")
    assert paper_matches_date_range(paper, None, date(2023, 12, 31))


def test_undated_papers_excluded_by_default_and_kept_on_request():
    paper = make_paper(publication_date_iso=None)
    assert not paper_matches_date_range(paper, date(2020, 1, 1), None)
    assert paper_matches_date_range(paper, date(2020, 1, 1), None, include_undated=True)
