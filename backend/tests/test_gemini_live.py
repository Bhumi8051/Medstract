"""Opt-in end-to-end test against REAL PubMed and REAL Gemini.

Skipped by default. It uses your GEMINI_API_KEY from backend/.env and counts
against your free-tier quota (one request). Run it with:

    RUN_GEMINI_LIVE=1 .venv/bin/python -m pytest tests/test_gemini_live.py -v
"""

import os

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.routers.deps import get_ai_usage_guard, require_user

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_GEMINI_LIVE") != "1" or not get_settings().gemini_key_value,
    reason="Live Gemini test: set RUN_GEMINI_LIVE=1 and GEMINI_API_KEY in backend/.env",
)


def test_live_analysis_of_a_real_paper():
    # Analysis requires login and spends usage (Step B). Use a stand-in user and an
    # always-allowing usage guard so this test doesn't create accounts in your database.
    from tests.test_analysis import FAKE_USER, AllowAllUsage

    app.dependency_overrides[require_user] = lambda: FAKE_USER
    app.dependency_overrides[get_ai_usage_guard] = lambda: AllowAllUsage()
    try:
        with TestClient(app) as client:  # runs the real startup (PubMed + Gemini clients)
            response = client.post("/api/papers/30903363/analyze", json={"summary_level": "college"}, timeout=120)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["pmid"] == "30903363"
    assert data["abstract_available"] is True
    assert data["report"]["key_findings"]
    assert all(p["basis"] in {"reported", "interpretation", "not_reported"} for p in data["report"]["methods"])
    assert get_settings().gemini_key_value not in response.text
