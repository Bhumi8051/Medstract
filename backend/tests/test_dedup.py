from app.models import NO_TITLE_PLACEHOLDER
from app.services.dedup import deduplicate_papers
from app.services.text import normalize_doi
from tests.conftest import make_paper


def test_duplicate_pmid_removed():
    papers = [make_paper("1", "First title here for test"), make_paper("1", "First title here for test")]
    unique, removed = deduplicate_papers(papers)
    assert [p.pmid for p in unique] == ["1"]
    assert removed == 1


def test_duplicate_doi_removed_ignoring_case_and_prefix():
    a = make_paper("1", "Asthma outcomes in children", doi="10.1000/ABC.123")
    b = make_paper("2", "A completely different title", doi="https://doi.org/10.1000/abc.123")
    unique, removed = deduplicate_papers([a, b])
    assert [p.pmid for p in unique] == ["1"]
    assert removed == 1


def test_duplicate_normalized_title_removed():
    a = make_paper("1", "Metformin and Cancer: A Systematic Review.")
    b = make_paper("2", "metformin and cancer -- a systematic review")
    unique, removed = deduplicate_papers([a, b])
    assert [p.pmid for p in unique] == ["1"]
    assert removed == 1


def test_different_dois_with_same_title_are_still_duplicates_by_title():
    a = make_paper("1", "Metformin and cancer: a systematic review", doi="10.1/a")
    b = make_paper("2", "Metformin and cancer: a systematic review", doi="10.1/b")
    assert len(deduplicate_papers([a, b])[0]) == 1


def test_short_generic_titles_are_not_merged():
    papers = [make_paper("1", "Erratum."), make_paper("2", "Erratum."), make_paper("3", "Editorial")]
    unique, removed = deduplicate_papers(papers)
    assert len(unique) == 3
    assert removed == 0


def test_placeholder_titles_are_not_merged():
    papers = [make_paper("1", NO_TITLE_PLACEHOLDER), make_paper("2", NO_TITLE_PLACEHOLDER)]
    assert len(deduplicate_papers(papers)[0]) == 2


def test_record_with_abstract_replaces_one_without_but_keeps_position():
    first = make_paper("1", "Some other paper about asthma")
    no_abstract = make_paper("2", "Metformin and cancer: a review", doi="10.1/x")
    with_abstract = make_paper("3", "Metformin and cancer: a review", doi="10.1/x", abstract="Text.")
    unique, removed = deduplicate_papers([first, no_abstract, with_abstract])
    assert [p.pmid for p in unique] == ["1", "3"]
    assert removed == 1


def test_order_preserved_and_empty_input():
    papers = [make_paper(str(i), f"Distinct paper title number {i}") for i in range(4)]
    assert [p.pmid for p in deduplicate_papers(papers)[0]] == ["0", "1", "2", "3"]
    assert deduplicate_papers([]) == ([], 0)


def test_normalize_doi_variants():
    assert normalize_doi(" DOI: 10.1/AbC ") == "10.1/abc"
    assert normalize_doi("http://dx.doi.org/10.1/abc") == "10.1/abc"
    assert normalize_doi("") is None
    assert normalize_doi(None) is None
