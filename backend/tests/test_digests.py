"""Step C endpoints: digest preview and manual test emails.

Runs against the PostgreSQL test database. PubMed, Gemini and the email sender
are all mocked: no network, no API keys, and no real email is ever sent.
"""

import json
import re
from datetime import date

import httpx
import pytest

from app.config import get_settings
from app.main import app
from app.routers.analysis import get_report_generator
from app.routers.digests import get_email_sender, get_email_test_limiter
from app.routers.search import get_pubmed_client, get_today
from app.services.auth import SlidingWindowLimiter
from app.services.email import EmailRejectedError, SentEmail
from app.services.gemini import AnalysisUnavailableError
from tests.conftest import article_xml, efetch_xml, esearch_json, make_client, make_settings, run_db

PASSWORD = "correct horse battery"
ME = "ada@example.org"
KEY = "re_test_SECRET_key_123456"
TODAY = date(2026, 10, 24)
RECENT = {"year": "2026", "month": "Oct", "day": "20"}  # inside the past week
OLD = {"year": "2019"}

ARTICLES = {
    "101": article_xml("101", "Leg cancer outcomes in adults", abstract="Outcomes of leg cancer were reviewed.", **RECENT),
    "102": article_xml("102", "Leg cancer imaging", abstract="Imaging of leg cancer in a cohort.", **RECENT),
    "201": article_xml("201", "Leg cancer history", abstract="An older review of leg cancer.", **OLD),
    "301": article_xml("301", "Leg cancer without abstract", **RECENT),
}


class FakeGenerator:
    """Summarizes every PMID in the prompt (no numbers, so the grounding check passes)."""

    model = "fake-gemini"

    def __init__(self) -> None:
        self.calls = 0
        self.error: Exception | None = None
        self.raw: str | None = None

    async def generate(self, *, prompt: str, **_):
        self.calls += 1
        if self.error:
            raise self.error
        if self.raw is not None:
            return self.raw
        pmids = re.findall(r'"pmid": "(\d+)"', prompt)
        return json.dumps({"summaries": [{"pmid": p, "summary": f"The authors report on paper {p}."} for p in pmids]})


class FakeSender:
    def __init__(self) -> None:
        self.sent = []
        self.error: Exception | None = None

    async def send(self, message, *, idempotency_key: str) -> SentEmail:
        if self.error:
            raise self.error
        self.sent.append((message, idempotency_key))
        return SentEmail(provider_message_id="msg_fake_1")


class PubMed:
    """Mock NCBI. `recent` answers date-filtered searches, `any_date` the rest."""

    def __init__(self) -> None:
        self.recent = ["101", "102"]
        self.any_date = ["201"]
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            return httpx.Response(500)
        if request.url.path.endswith("esearch.fcgi"):
            ids = self.recent if "mindate" in request.url.params else self.any_date
            return httpx.Response(200, json=esearch_json(ids))
        wanted = request.url.params.get("id", "").split(",")
        return httpx.Response(200, text=efetch_xml(*(ARTICLES[i] for i in wanted if i in ARTICLES)))


@pytest.fixture
def env(db_client):
    pubmed, generator, sender = PubMed(), FakeGenerator(), FakeSender()
    settings = {"value": make_settings(email_enabled=True, resend_api_key=KEY, email_test_recipients=ME)}
    app.dependency_overrides[get_pubmed_client] = lambda: make_client(pubmed.handler)
    app.dependency_overrides[get_report_generator] = lambda: generator
    app.dependency_overrides[get_email_sender] = lambda: sender
    app.dependency_overrides[get_settings] = lambda: settings["value"]
    app.dependency_overrides[get_today] = lambda: TODAY

    class Env:
        client = db_client
        gen = generator
        mail = sender
        ncbi = pubmed

        @staticmethod
        def use(**overrides):
            values = {"email_enabled": True, "resend_api_key": KEY, "email_test_recipients": ME, **overrides}
            settings["value"] = make_settings(**values)

        @staticmethod
        def ai_used() -> int:
            return int(run_db("SELECT coalesce(sum(used), 0) FROM ai_usage_daily")[0][0])

    yield Env
    app.dependency_overrides.clear()


def sign_up(client, email: str = ME) -> None:
    response = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text


def subscribe(client, topic: str = "leg cancer", **fields) -> str:
    body = {
        "topic": topic,
        "frequency": "weekly",
        "weekday": 1,
        "delivery_time": "23:30",
        "time_zone": "America/New_York",
        "paper_count": 5,
        "reading_level": "college",
        **fields,
    }
    response = client.post("/api/subscriptions", json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def send(client, *ids: str, **extra):
    return client.post("/api/digests/test-send", json={"subscription_ids": list(ids), **extra})


def preview(client, *ids: str):
    return client.post("/api/digests/preview", json={"subscription_ids": list(ids)})


# ---------------------------------------------------------------- access


def test_everything_requires_login(env):
    assert env.client.get("/api/digests/email-status").status_code == 401
    assert preview(env.client, "00000000-0000-0000-0000-000000000000").status_code == 401
    assert send(env.client, "00000000-0000-0000-0000-000000000000").status_code == 401
    assert env.mail.sent == []


def test_changes_require_the_csrf_header(env):
    sign_up(env.client)
    sub = subscribe(env.client)
    del env.client.headers["X-Requested-With"]
    assert send(env.client, sub).status_code == 403
    assert preview(env.client, sub).status_code == 403
    assert env.mail.sent == [] and env.gen.calls == 0


def test_email_status_never_reveals_the_key(env):
    sign_up(env.client)
    response = env.client.get("/api/digests/email-status")
    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "configured": True,
        "recipient": ME,
        "recipient_allowed": True,
        "sender": "Healthcare Research Agent <onboarding@resend.dev>",
        "test_sender": True,
        "sends_per_hour": 5,
        "automatic_delivery_active": False,
    }
    assert KEY not in response.text


# ---------------------------------------------------------------- preview


def test_preview_builds_the_digest_and_sends_nothing(env):
    sign_up(env.client)
    sub = subscribe(env.client)
    response = preview(env.client, sub)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["subject"] == "Research digest (test): leg cancer"
    assert data["model"] == "fake-gemini"
    [section] = data["sections"]
    assert section["topic"] == "leg cancer" and section["window"] == "Past week"
    assert section["used_fallback"] is False and section["ai_status"] == "generated"
    assert [p["pmid"] for p in section["papers"]] == ["101", "102"]
    paper = section["papers"][0]
    assert paper["pubmed_url"] == "https://pubmed.ncbi.nlm.nih.gov/101/"
    assert paper["ai_summary"] == "The authors report on paper 101."
    assert paper["journal"] == "Test Journal"
    assert env.mail.sent == []
    assert env.gen.calls == 1 and env.ai_used() == 1  # one AI unit per subscription, not per paper


def test_preview_works_even_when_email_is_off(env):
    env.use(email_enabled=False, resend_api_key=None, email_test_recipients="")
    sign_up(env.client)
    assert preview(env.client, subscribe(env.client)).status_code == 200


# ---------------------------------------------------------------- test send


def test_test_send_goes_only_to_the_account_email(env):
    sign_up(env.client)
    sub = subscribe(env.client)
    response = send(env.client, sub)
    assert response.status_code == 200, response.text
    assert response.json()["sent_to"] == ME
    assert response.json()["provider_message_id"] == "msg_fake_1"
    [(message, idempotency_key)] = env.mail.sent
    assert message.to == ME
    assert message.subject == "Research digest (test): leg cancer"
    assert "Leg cancer outcomes in adults" in message.html and "https://pubmed.ncbi.nlm.nih.gov/101/" in message.text
    assert "The authors report on paper 101." in message.html
    assert idempotency_key.startswith("test-digest-")
    assert KEY not in response.text


@pytest.mark.parametrize("field", ["to", "recipient", "email"])
def test_recipient_cannot_be_chosen_in_the_request(env, field):
    sign_up(env.client)
    sub = subscribe(env.client)
    response = send(env.client, sub, **{field: "victim@example.org"})
    assert response.status_code == 422
    assert env.mail.sent == []


def test_disabled_email_sends_nothing_and_uses_no_ai(env):
    env.use(email_enabled=False)
    sign_up(env.client)
    response = send(env.client, subscribe(env.client))
    assert response.status_code == 503 and "EMAIL_ENABLED" in response.json()["detail"]
    assert env.mail.sent == [] and env.gen.calls == 0 and env.ai_used() == 0


def test_missing_key_sends_nothing(env):
    env.use(resend_api_key=None)
    sign_up(env.client)
    response = send(env.client, subscribe(env.client))
    assert response.status_code == 503 and "RESEND_API_KEY" in response.json()["detail"]
    assert env.mail.sent == [] and env.gen.calls == 0


def test_addresses_not_on_the_allowlist_are_refused(env):
    sign_up(env.client, "someone.else@example.org")
    sub = subscribe(env.client)
    status = env.client.get("/api/digests/email-status").json()
    assert status["recipient_allowed"] is False
    response = send(env.client, sub)
    assert response.status_code == 403 and "EMAIL_TEST_RECIPIENTS" in response.json()["detail"]
    assert env.mail.sent == [] and env.gen.calls == 0


def test_allowlist_is_case_insensitive(env):
    env.use(email_test_recipients="  ADA@Example.ORG ")
    sign_up(env.client)
    assert send(env.client, subscribe(env.client)).status_code == 200


def test_another_users_subscription_is_not_found(env):
    sign_up(env.client, "other@example.org")
    theirs = subscribe(env.client)
    env.client.post("/api/auth/logout")
    sign_up(env.client)
    mine = subscribe(env.client)
    assert send(env.client, mine, theirs).status_code == 404
    assert preview(env.client, theirs).status_code == 404
    assert env.mail.sent == [] and env.gen.calls == 0


@pytest.mark.parametrize("ids", [[], ["a", "b"], None])
def test_invalid_subscription_lists_are_rejected(env, ids):
    sign_up(env.client)
    body = {} if ids is None else {"subscription_ids": ids}
    assert env.client.post("/api/digests/test-send", json=body).status_code == 422


def test_at_most_three_subscriptions_per_digest(env):
    sign_up(env.client)
    subs = [subscribe(env.client, f"leg cancer {n}") for n in range(4)]
    assert send(env.client, *subs).status_code == 422
    response = send(env.client, *subs[:3])
    assert response.status_code == 200
    assert response.json()["digest"]["subject"] == "Research digest (test): 3 topics"
    assert env.gen.calls == 3 and env.ai_used() == 3


def test_test_sends_are_rate_limited_per_hour(env):
    app.dependency_overrides[get_email_test_limiter] = lambda: limiter
    limiter = SlidingWindowLimiter(2, 3600)
    sign_up(env.client)
    sub = subscribe(env.client)
    assert send(env.client, sub).status_code == 200
    assert send(env.client, sub).status_code == 200
    blocked = send(env.client, sub)
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0
    assert len(env.mail.sent) == 2 and env.gen.calls == 2  # the blocked attempt used no AI


def test_provider_failure_is_a_safe_502(env):
    env.mail.error = EmailRejectedError("The email service refused to send this email.")
    sign_up(env.client)
    response = send(env.client, subscribe(env.client))
    assert response.status_code == 502
    assert response.json() == {"detail": "The email service refused to send this email."}
    assert KEY not in response.text


def test_pubmed_outage_sends_nothing(env):
    env.ncbi.down = True
    sign_up(env.client)
    response = send(env.client, subscribe(env.client))
    assert response.status_code == 502
    assert env.mail.sent == [] and env.gen.calls == 0


# ---------------------------------------------------------------- digest content


def test_empty_window_falls_back_to_any_date(env):
    env.ncbi.recent = []
    sign_up(env.client)
    data = preview(env.client, subscribe(env.client)).json()
    [section] = data["sections"]
    assert section["used_fallback"] is True
    assert section["window"] == "Any date (nothing found in the past week)"
    assert [p["pmid"] for p in section["papers"]] == ["201"]


def test_monthly_subscriptions_use_the_past_month(env):
    sign_up(env.client)
    sub = subscribe(env.client, frequency="monthly", month_day=1, weekday=None)
    assert preview(env.client, sub).json()["sections"][0]["window"] == "Past month"


def test_gemini_failure_still_sends_with_excerpts_and_refunds(env):
    env.gen.error = AnalysisUnavailableError("The AI service is temporarily unavailable. Please try again shortly.")
    sign_up(env.client)
    response = send(env.client, subscribe(env.client))
    assert response.status_code == 200
    section = response.json()["digest"]["sections"][0]
    assert section["ai_status"] == "failed"
    assert section["ai_note"].startswith("AI summaries unavailable:")
    assert all(p["ai_summary"] is None and p["abstract_excerpt"] for p in section["papers"])
    assert env.ai_used() == 0  # refunded
    assert "From the abstract:" in env.mail.sent[0][0].html


def test_unusable_ai_output_is_refunded(env):
    env.gen.raw = "this is not json"
    sign_up(env.client)
    section = preview(env.client, subscribe(env.client)).json()["sections"][0]
    assert section["ai_status"] == "failed" and env.ai_used() == 0


def test_daily_ai_limit_reached_still_builds_the_digest(env):
    env.use(ai_daily_limit_per_user=1)
    sign_up(env.client)
    sub = subscribe(env.client)
    assert preview(env.client, sub).json()["sections"][0]["ai_status"] == "generated"
    section = send(env.client, sub).json()["digest"]["sections"][0]
    assert section["ai_status"] == "limit_reached"
    assert "AI analyses for today" in section["ai_note"]
    assert env.gen.calls == 1 and env.ai_used() == 1
    assert len(env.mail.sent) == 1


def test_summaries_with_invented_numbers_are_withheld(env):
    env.gen.raw = json.dumps(
        {"summaries": [{"pmid": "101", "summary": "The authors studied 999 patients."},
                       {"pmid": "102", "summary": "A cohort imaging study."}]}
    )
    sign_up(env.client)
    papers = preview(env.client, subscribe(env.client)).json()["sections"][0]["papers"]
    assert papers[0]["ai_summary"] is None and "numbers" in papers[0]["summary_note"]
    assert papers[0]["abstract_excerpt"] == "Outcomes of leg cancer were reviewed."
    assert papers[1]["ai_summary"] == "A cohort imaging study."


def test_papers_without_abstracts_need_no_ai(env):
    env.ncbi.recent = ["301"]
    sign_up(env.client)
    section = preview(env.client, subscribe(env.client)).json()["sections"][0]
    assert section["ai_status"] == "not_needed" and env.gen.calls == 0 and env.ai_used() == 0
    assert section["papers"][0]["summary_note"] == "No abstract available in PubMed."


def test_paper_count_and_reading_level_come_from_the_subscription(env):
    env.ncbi.recent = ["101", "102"]
    prompts = []
    original = env.gen.generate

    async def capture(**kwargs):
        prompts.append(kwargs["system_instruction"])
        return await original(**kwargs)

    env.gen.generate = capture
    sign_up(env.client)
    sub = subscribe(env.client, reading_level="high_school", paper_count=5)
    preview(env.client, sub)
    assert "high-school" in prompts[0]
