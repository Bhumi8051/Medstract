"""Test runs can never start the digest scheduler or send real email.

tests/conftest.py forces DIGEST_SCHEDULER_ENABLED=false, DIGEST_DELIVERY_MODE=off,
EMAIL_ENABLED=false and RESEND_API_KEY= before any settings exist, and clears the
settings cache. These tests prove that holds even when the shell environment and
backend/.env ask for the opposite (backend/.env does enable email on the owner's
machine). Nothing here makes a network request.
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.email import EmailMessage, EmailNotConfiguredError
from tests.conftest import TEST_SAFETY_ENV

BACKEND = Path(__file__).resolve().parent.parent
DANGEROUS_ENV = {
    "DIGEST_SCHEDULER_ENABLED": "true",
    "DIGEST_DELIVERY_MODE": "allowlist",
    "EMAIL_ENABLED": "true",
    "RESEND_API_KEY": "re_shell_requested_key_123456",
}


def test_settings_in_this_test_run_are_safe():
    settings = get_settings()
    assert settings.digest_scheduler_enabled is False
    assert settings.digest_delivery_mode == "off"
    assert settings.email_enabled is False
    assert settings.resend_key_value is None
    assert {k: os.environ[k] for k in TEST_SAFETY_ENV} == TEST_SAFETY_ENV


def test_the_real_app_startup_has_no_scheduler_and_cannot_email():
    with TestClient(app) as client:
        assert app.state.digest_scheduler is None
        assert client.get("/health").json()["digest_scheduler"]["enabled"] is False
        sender = app.state.email_sender  # the real Resend sender the app built at startup
        with pytest.raises(EmailNotConfiguredError):
            # Refused before any HTTP request: there is no key.
            asyncio.run(sender.send(EmailMessage(to="x@example.org", subject="s", html="h", text="t"),
                                    idempotency_key="k"))


def _probe(code: str) -> str:
    """Run Python in a fresh process whose environment requests the dangerous settings."""
    env = {**os.environ, **DANGEROUS_ENV}
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout.strip().splitlines()[-1]


SHOW = (
    "s = get_settings(); print(s.digest_scheduler_enabled, s.digest_delivery_mode, s.email_enabled, "
    "s.resend_key_value is None)"
)


def test_shell_environment_cannot_override_the_guard():
    out = _probe(f"import tests.conftest\nfrom app.config import get_settings\n{SHOW}")
    assert out == "False off False True"


def test_settings_cached_before_the_guard_are_discarded():
    # Settings created (and cached) with the dangerous values BEFORE conftest runs...
    code = (
        "from app.config import get_settings\n"
        "before = get_settings(); assert before.email_enabled and before.digest_scheduler_enabled\n"
        "import tests.conftest\n"
        f"{SHOW}"
    )
    # ...are replaced once the guard runs.
    assert _probe(code) == "False off False True"


def test_without_the_guard_the_environment_would_have_enabled_everything():
    """Control: proves the probe really sets the dangerous values (so the tests above mean something)."""
    out = _probe(f"from app.config import get_settings\n{SHOW}")
    assert out == "True allowlist True False"
