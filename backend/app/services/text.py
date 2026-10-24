"""Text normalization shared by ranking and deduplication."""

import re
import unicodedata

# Common English words plus PubMed boolean operators; they carry no topic signal.
_STOPWORDS = frozenset(
    """
    a an and are as at be been but by can do does for from has have how in into is it
    its of on or not that the their them these this those to was were what when which
    who why will with within without between among versus vs via than then there
    """.split()
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")
# PubMed field tags in queries, e.g. "asthma[tiab]" or "[MeSH Terms]".
_FIELD_TAG_RE = re.compile(r"\[[^\]]*\]")
_DOI_PREFIX_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)


def normalize_text(text: str) -> str:
    """Lowercase and strip accents, e.g. 'Sjögren' -> 'sjogren'."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _stem(token: str) -> str:
    """Very light plural stemming so 'cancers' matches 'cancer' and 'studies' matches 'study'."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def tokenize(text: str | None) -> list[str]:
    """Split text into normalized keyword tokens, dropping stopwords and single letters."""
    if not text:
        return []
    tokens = _TOKEN_RE.findall(normalize_text(text))
    return [_stem(t) for t in tokens if t not in _STOPWORDS and (len(t) > 1 or t.isdigit())]


def tokenize_query(query: str) -> list[str]:
    """Like tokenize(), but first removes PubMed field tags such as [tiab]."""
    return tokenize(_FIELD_TAG_RE.sub(" ", query))


def normalize_title(title: str | None) -> str:
    """Title reduced to lowercase words separated by single spaces (for duplicate detection)."""
    if not title:
        return ""
    return " ".join(_TOKEN_RE.findall(normalize_text(title)))


def normalize_doi(doi: str | None) -> str | None:
    """Canonical DOI: lowercase, no 'https://doi.org/' or 'doi:' prefix."""
    if not doi:
        return None
    cleaned = _DOI_PREFIX_RE.sub("", doi.strip()).strip().lower()
    return cleaned or None
