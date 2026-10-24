from app.models import NO_TITLE_PLACEHOLDER
from app.services.ranking import rank_papers, score_paper
from app.services.text import tokenize, tokenize_query
from tests.conftest import make_paper


def test_title_match_outranks_abstract_only_match():
    abstract_only = make_paper("1", "Unrelated heading", abstract="Metformin reduces cancer risk.")
    title_match = make_paper("2", "Metformin and cancer", abstract="Some text.")

    ranked = rank_papers("metformin cancer", [abstract_only, title_match])

    assert [p.pmid for p in ranked] == ["2", "1"]
    assert ranked[0].relevance_score > ranked[1].relevance_score


def test_scores_use_title_and_abstract_weights():
    terms = set(tokenize_query("metformin cancer"))
    both = make_paper(title="Metformin and cancer", abstract="Metformin in cancer patients.")
    title_only = make_paper(title="Metformin and cancer")
    abstract_only = make_paper(title="Other", abstract="metformin cancer")

    assert score_paper(terms, both) == 1.0
    assert score_paper(terms, title_only) == 0.75  # 3 / (3 + 1)
    assert score_paper(terms, abstract_only) == 0.25  # 1 / (3 + 1)
    assert score_paper(terms, title_only, title_weight=1, abstract_weight=1) == 0.5


def test_partial_overlap_scores_proportionally():
    terms = set(tokenize_query("metformin breast cancer"))
    paper = make_paper(title="Breast cancer outcomes")  # 2 of 3 terms in title
    assert score_paper(terms, paper) == round(0.75 * 2 / 3, 4)


def test_normalization_handles_case_plurals_punctuation_and_accents():
    assert tokenize("Cancers, STUDIES & Sjögren's!") == tokenize("cancer study sjogren s")
    paper = make_paper(title="CANCERS in Diabetic Cohorts")
    ranked = rank_papers("cancer cohort", [paper])
    assert ranked[0].relevance_score == 0.75


def test_query_field_tags_and_boolean_operators_are_ignored():
    assert tokenize_query("asthma[tiab] AND children[MeSH Terms] NOT adults") == [
        "asthma",
        "children",
        "adult",
    ]


def test_stopword_only_query_scores_zero_and_keeps_pubmed_order():
    papers = [make_paper("1", "The first"), make_paper("2", "The second")]
    ranked = rank_papers("the of and", papers)
    assert [p.pmid for p in ranked] == ["1", "2"]
    assert all(p.relevance_score == 0.0 for p in ranked)


def test_ties_keep_original_pubmed_order():
    papers = [make_paper(str(i), "Asthma in children") for i in range(5)]
    assert [p.pmid for p in rank_papers("asthma children", papers)] == ["0", "1", "2", "3", "4"]


def test_missing_abstract_and_placeholder_title_do_not_crash():
    terms = set(tokenize_query("title available"))
    paper = make_paper(title=NO_TITLE_PLACEHOLDER, abstract=None)
    assert score_paper(terms, paper) == 0.0


def test_ranking_does_not_mutate_input():
    paper = make_paper(title="Asthma")
    rank_papers("asthma", [paper])
    assert paper.relevance_score is None


def test_empty_paper_list():
    assert rank_papers("asthma", []) == []
