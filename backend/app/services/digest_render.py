"""Render a DigestOut as an email: simple inline-styled HTML plus a plain-text version.

Everything that comes from PubMed or Gemini is HTML-escaped, and only https://
links are rendered, so a paper title like "<script>" shows up as text.
"""

from datetime import UTC, datetime
from html import escape

from app.models import DigestAiStatus, DigestOut, DigestPaper, DigestSection
from app.services.analysis import LEVEL_LABELS

BRAND = "Medstract"
BRAND_NAVY = "#0b2e4f"  # the logo's colour, rgb(11,46,79)
# "(Test)" keeps manual test emails clearly apart from scheduled ones.
TEST_SUBJECT_PREFIX = f"{BRAND} Research Digest (Test)"
SCHEDULED_SUBJECT_PREFIX = f"{BRAND} Research Digest"

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


SCHEDULED_NOTICE = (
    "This is your scheduled research digest. Automatic delivery is in a limited test: "
    "it only goes to approved addresses."
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
    if not section.papers and not section.ai_note:
        parts.append(f'<p style="{_MUTED}">No PubMed papers matched this topic.</p>')
    parts.extend(_paper_html(p) for p in section.papers)
    return "".join(parts)


def _footer_html(unsubscribe_url: str | None, manage_url: str | None) -> str:
    # Both URLs come from our own settings (PUBLIC_APP_URL), not from PubMed or
    # Gemini, so http://localhost is allowed here (unlike paper links).
    links = [
        f'<a href="{_e(url)}" style="color:#0f766e;">{label}</a>'
        for url, label in ((unsubscribe_url, "Unsubscribe from this topic"), (manage_url, "Manage your subscriptions"))
        if url
    ]
    if not links:
        return ""
    return f'<p style="margin:16px 0 0;font-size:12px;{_MUTED}">{" · ".join(links)}</p>'


# The brand is a styled text wordmark, not an image: the logo files are SVG, which
# Gmail and Outlook don't display, and an inline/hosted PNG needs attachments or a
# public https URL. Text renders in every mail client.
_BRAND_HTML = (
    f'<p style="margin:0 0 16px;padding:0 0 12px;border-bottom:3px solid {BRAND_NAVY};'
    f'font-size:22px;font-weight:800;letter-spacing:3px;color:{BRAND_NAVY};">{BRAND.upper()}</p>'
)
def _sent_line(generated_at: datetime) -> str:
    """The footer's last line. The time makes every email's ending different: Gmail
    collapses an ending it has seen before (behind "•••"), which hid the footer link."""
    when = generated_at.astimezone(UTC)
    return f"Sent by {BRAND} on {when:%b} {when.day}, {when:%Y} at {when:%H:%M} UTC. Research digests from PubMed."


EXPLORE_LINE = f"Explore more research with {BRAND}."
VISIT_LABEL = f"Visit {BRAND}"


def _app_link(app_url: str) -> str | None:
    """PUBLIC_APP_URL as an absolute link, or None if it isn't one (a relative link
    does nothing in an email). Set it to the https:// address in production."""
    url = app_url.strip().rstrip("/")
    return f"{url}/" if url.startswith(("https://", "http://")) else None


def _brand_footer_html(app_url: str, generated_at: datetime) -> str:
    """The Medstract footer shared by every digest email (test and scheduled)."""
    url = _app_link(app_url)
    visit = (
        f'<a href="{_e(url)}" style="color:#0f766e;font-weight:600;">{VISIT_LABEL}</a>' if url else VISIT_LABEL
    )
    return (
        f'<div style="margin:24px 0 0;padding:16px 0 0;border-top:1px solid #e2e8f0;font-size:12px;{_MUTED}">'
        f'<p style="margin:0;">{_e(EXPLORE_LINE)} {visit}</p>'
        f'<p style="margin:8px 0 0;">{_e(_sent_line(generated_at))}</p>'
        "</div>"
    )


def _brand_footer_text(app_url: str, generated_at: datetime) -> list[str]:
    url = _app_link(app_url)
    return ["", "-" * 60, EXPLORE_LINE, f"{VISIT_LABEL}: {url}" if url else VISIT_LABEL, "", _sent_line(generated_at)]


def render_html(
    digest: DigestOut,
    notice: str = TEST_NOTICE,
    *,
    app_url: str,
    unsubscribe_url: str | None = None,
    manage_url: str | None = None,
) -> str:
    return (
        f"<!doctype html><html><head><title>{_e(digest.subject)}</title></head><body "
        f'style="margin:0;padding:24px;background:#f8fafc;color:#0f172a;{_FONT}line-height:1.5;">'
        '<div style="max-width:640px;margin:0 auto;background:#ffffff;padding:24px;border-radius:12px;">'
        + _BRAND_HTML
        + f'<h1 style="margin:0;font-size:22px;">{_e(digest.subject)}</h1>'
        f'<p style="margin:8px 0 0;padding:8px 12px;background:#e0f2fe;border-radius:6px;font-size:13px;">{_e(notice)}</p>'
        + "".join(_section_html(s) for s in digest.sections)
        + f'<p style="margin:24px 0 0;font-size:12px;{_MUTED}">{_e(SOURCE_NOTE)} {_e(digest.disclaimer)}</p>'
        + _footer_html(unsubscribe_url, manage_url)
        + _brand_footer_html(app_url, digest.generated_at)
        + "</div></body></html>"
    )


def render_text(
    digest: DigestOut,
    notice: str = TEST_NOTICE,
    *,
    app_url: str,
    unsubscribe_url: str | None = None,
    manage_url: str | None = None,
) -> str:
    lines = [BRAND.upper(), "=" * len(BRAND), "", digest.subject, "", notice, ""]
    for section in digest.sections:
        lines += [
            "=" * 60,
            section.topic,
            f"{section.window} · {LEVEL_LABELS[section.reading_level]} reading level · {len(section.papers)} papers",
        ]
        if section.ai_note and section.ai_status is not DigestAiStatus.GENERATED:
            lines.append(section.ai_note)
        lines.append("")
        if not section.papers and not section.ai_note:
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
    if unsubscribe_url:
        lines.append(f"Unsubscribe from this topic: {unsubscribe_url}")
    if manage_url:
        lines.append(f"Manage your subscriptions: {manage_url}")
    lines += _brand_footer_text(app_url, digest.generated_at)
    return "\n".join(lines)
