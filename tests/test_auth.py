"""Acceptance tests for optional bearer token auth (Issue #3).

Tests verify:
AC-1: Token set + no header → 401
AC-2: Token set + correct header → 200
AC-3: Token set + wrong header → 401
AC-4: Token unset + no header → 200 (dev mode)
AC-5: Dashboard (/) always returns 200 regardless of auth
AC-6: Auth applies to all API routes
AC-7: [review-gate] Token read from os.environ (checked via source inspection)
"""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def app_with_token():
    """Create a test client with ATTENTIONOS_TOKEN set."""
    with patch.dict(os.environ, {"ATTENTIONOS_TOKEN": "secret123"}):
        # Re-import to pick up the fresh app (auth reads token at request time)
        from src.api.main import app

        yield TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def app_no_token():
    """Create a test client with ATTENTIONOS_TOKEN unset."""
    env = os.environ.copy()
    env.pop("ATTENTIONOS_TOKEN", None)
    with patch.dict(os.environ, env, clear=True):
        from src.api.main import app

        yield TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# AC-1: Token set + no header → 401
# ---------------------------------------------------------------------------


def test_api_returns_401_without_header_when_token_set(app_with_token):
    resp = app_with_token.get("/api/articles")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
    assert resp.json()["detail"] == "Not authenticated"


# ---------------------------------------------------------------------------
# AC-2: Token set + correct header → 200
# ---------------------------------------------------------------------------


def test_api_returns_200_with_correct_bearer_when_token_set(app_with_token):
    resp = app_with_token.get(
        "/api/articles",
        headers={"Authorization": "Bearer secret123"},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"


# ---------------------------------------------------------------------------
# AC-3: Token set + wrong header → 401
# ---------------------------------------------------------------------------


def test_api_returns_401_with_wrong_bearer_when_token_set(app_with_token):
    resp = app_with_token.get(
        "/api/articles",
        headers={"Authorization": "Bearer wrongtoken"},
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


# ---------------------------------------------------------------------------
# AC-4: Token unset + no header → 200 (dev mode)
# ---------------------------------------------------------------------------


def test_api_returns_200_without_header_when_token_unset(app_no_token):
    resp = app_no_token.get("/api/articles")
    assert resp.status_code == 200, f"Expected 200 (dev mode), got {resp.status_code}"


# ---------------------------------------------------------------------------
# AC-5: Dashboard always returns 200
# ---------------------------------------------------------------------------


def test_dashboard_returns_200_with_token_set_no_header(app_with_token):
    resp = app_with_token.get("/")
    assert resp.status_code == 200, f"Dashboard should be 200, got {resp.status_code}"


def test_dashboard_returns_200_with_token_unset(app_no_token):
    resp = app_no_token.get("/")
    assert resp.status_code == 200, f"Dashboard should be 200, got {resp.status_code}"


# ---------------------------------------------------------------------------
# AC-6: Auth applies to all API routes
# ---------------------------------------------------------------------------

API_ROUTES_GET = [
    "/api/articles",
    "/api/feeds",
    "/api/sections",
    "/api/stats",
]

# Write routes: only test 401 (not 200 — they need valid bodies or trigger side effects)
API_ROUTES_WRITE = [
    ("POST", "/api/feeds"),
    ("DELETE", "/api/feeds/999"),
    ("POST", "/api/scores"),
    ("POST", "/api/feedback"),
    ("PUT", "/api/sections"),
]


@pytest.mark.parametrize("path", API_ROUTES_GET)
def test_all_api_get_routes_require_auth_when_token_set(app_with_token, path):
    resp = app_with_token.get(path)
    assert resp.status_code == 401, f"{path} should return 401 without token, got {resp.status_code}"


@pytest.mark.parametrize("path", API_ROUTES_GET)
def test_all_api_get_routes_pass_with_correct_token(app_with_token, path):
    resp = app_with_token.get(path, headers={"Authorization": "Bearer secret123"})
    assert resp.status_code == 200, f"{path} should return 200 with correct token, got {resp.status_code}"


@pytest.mark.parametrize("method,path", API_ROUTES_WRITE)
def test_write_routes_require_auth_when_token_set(app_with_token, method, path):
    resp = getattr(app_with_token, method.lower())(path)
    assert resp.status_code == 401, f"{method} {path} should return 401 without token, got {resp.status_code}"


# ---------------------------------------------------------------------------
# AC-7: [review-gate] Token read from os.environ
# ---------------------------------------------------------------------------


def test_auth_module_reads_from_environ():
    """Source-level check: auth.py reads token from os.environ, not hardcoded."""
    with open("src/api/auth.py", encoding="utf-8") as f:
        source = f.read()
    assert "os.environ" in source, "auth.py should read token from os.environ"
    assert "ATTENTIONOS_TOKEN" in source, "auth.py should reference ATTENTIONOS_TOKEN"
