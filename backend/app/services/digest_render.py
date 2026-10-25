"""Render a DigestOut as an email: simple inline-styled HTML plus a plain-text version.

Everything that comes from PubMed or Gemini is HTML-escaped, and only https://
links are rendered, so a paper title like "<script>" shows up as text.
"""

from html import escape

from app.models import DigestAiStatus, DigestOut, DigestPaper, DigestSection
from app.services.analysis import LEVEL_LABELS

TEST_NOTICE = (
    "This is a manual test digest you requested from your account page. "
    "Automatic daily, weekly and monthly delivery is not active yet."
)
SOURCE_NOTE = "Papers come from PubMed. AI summaries are based on the PubMed abstract only, not the full paper."

_FONT = "font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;"
_MUTED = "color:#475569;"


def _e(text: str | None) -> str:
    return escape(text or "", quote=True)


def _link(url: str | None, label: str) -> str:
    if not url or not url.startswith("https://"):
        return _e(label)
    return f'<a href="{_e(url)}" style="color:#0f766e;">{_e(label)}</a>'


def _details(paper: DigestPaper) -> str:
    """Authors · journal · date, as plain text."""
    return " · ".join(filter(None, [", ".join(paper.authors), paper.journal, paper.publication_date]))


def _paper_html(paper: DigestPaper) -> str:
    title = _link(paper.pubmed_url, paper.title)
    ids = [f"PMID {_link(paper.pubmed_url, paper.pmid)}"]
    if paper.doi:
        ids.append(f"DOI {_link(paper.doi_url, paper.doi)}")
    if paper.ai_summary:
        body = (
            f'<p style="margin:8px 0 0;"><strong>AI summary:</strong> {_e(paper.ai_summary)}</p>'
        )
    else:
        note = f'<p style="margin:8px 0 0;{_MUTED}font-style:italic;">{_e(paper.summary_note)}</p>' if paper.summary_note else ""
        text = (
            f'<p style="margin:8px 0 0;"><strong>From the abstract:</strong> {_e(paper.abstract_excerpt)}</p>'
            if paper.abstract_excerpt
            else ""
        )
        body = note + text
    return (
        '<div style="margin:0 0 20px;padding:0 0 16px;border-bottom:1px solid #e2e8f0;">'
        f'<p style="margin:0;font-size:16px;font-weight:600;">{title}</p>'
        f'<p style="margin:4px 0 0;font-size:13px;{_MUTED}">{_e(_details(paper))}</p>'
        f'<p style="margin:4px 0 0;font-size:13px;{_MUTED}">{" · ".join(ids)}</p>'
        f"{body}</div>"
    )


def _section_html(section: DigestSection) -> str:
    meta = f"{section.window} · {LEVEL_LABELS[section.reading_level]} reading level · {len(section.papers)} papers"
    parts = [
        f'<h2 style="margin:28px 0 4px;font-size:20px;">{_e(section.topic)}</h2>',
        f'<p style="margin:0 0 12px;font-size:13px;{_MUTED}">{_e(meta)}</p>',
    ]
    if section.ai_note and section.ai_status is not DigestAiStatus.GENERATED:
        parts.append(
            '<p style="margin:0 0 12px;padding:8px 12px;background:#fef3c7;border-radius:6px;font-size:13px;">'
            f"{_e(section.ai_note)}</p>"
        )
    if not section.papers:
        parts.append(f'<p style="{_MUTED}">No PubMed papers matched this topic.</p>')
    parts.extend(_paper_html(p) for p in section.papers)
    return "".join(parts)


def render_html(digest: DigestOut) -> str:
    return (
        "<!doctype html><html><body "
        f'style="margin:0;padding:24px;background:#f8fafc;color:#0f172a;{_FONT}line-height:1.5;">'
        '<div style="max-width:640px;margin:0 auto;background:#ffffff;padding:24px;border-radius:12px;">'
        f'<h1 style="margin:0;font-size:22px;">{_e(digest.subject)}</h1>'
        f'<p style="margin:8px 0 0;padding:8px 12px;background:#e0f2fe;border-radius:6px;font-size:13px;">{_e(TEST_NOTICE)}</p>'
        + "".join(_section_html(s) for s in digest.sections)
        + f'<p style="margin:24px 0 0;font-size:12px;{_MUTED}">{_e(SOURCE_NOTE)} {_e(digest.disclaimer)}</p>'
        "</div></body></html>"
    )


def render_text(digest: DigestOut) -> str:
    lines = [digest.subject, "", TEST_NOTICE, ""]
    for section in digest.sections:
        lines += [
            "=" * 60,
            section.topic,
            f"{section.window} · {LEVEL_LABELS[section.reading_level]} reading level · {len(section.papers)} papers",
        ]
        if section.ai_note and section.ai_status is not DigestAiStatus.GENERATED:
            lines.append(section.ai_note)
        lines.append("")
        if not section.papers:
            lines += ["No PubMed papers matched this topic.", ""]
        for paper in section.papers:
            lines.append(paper.title)
            if details := _details(paper):
                lines.append(details)
            lines.append(f"PubMed: {paper.pubmed_url}")
            if paper.doi_url:
                lines.append(f"DOI: {paper.doi_url}")
            if paper.ai_summary:
                lines.append(f"AI summary: {paper.ai_summary}")
            else:
                if paper.summary_note:
                    lines.append(paper.summary_note)
                if paper.abstract_excerpt:
                    lines.append(f"From the abstract: {paper.abstract_excerpt}")
            lines.append("")
    lines += ["-" * 60, SOURCE_NOTE, digest.disclaimer]
    return "\n".join(lines)
