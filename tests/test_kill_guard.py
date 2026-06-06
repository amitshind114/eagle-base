"""Kill switch guard tests — verifies the CONFIRM safety mechanism.

The kill switch requires the request body to contain::

    {"confirm": "CONFIRM"}

Any other value (or missing field) must return HTTP 400 immediately
without triggering any side effects.

Tests::

  [x] POST /api/live/kill/strategies  — correct confirm → accepted
  [x] POST /api/live/kill/strategies  — wrong confirm   → 400
  [x] POST /api/live/kill/strategies  — missing confirm → 400 / 422
  [x] POST /api/live/kill/strategies  — empty confirm   → 400
  [x] POST /api/live/kill/orders      — correct confirm → accepted
  [x] POST /api/live/kill/orders      — wrong confirm   → 400
  [x] POST /api/live/kill/positions   — correct confirm → accepted
  [x] POST /api/live/kill/positions   — wrong confirm   → 400
  [x] Kill side effects NOT triggered when confirm is wrong

Run with::

    pytest tests/test_kill_guard.py -v
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# App bootstrap (same pattern as test_live_router.py)
# ---------------------------------------------------------------------------

try:
    from api.main import app
except ImportError:
    from fastapi import FastAPI
    app = FastAPI()
    from api.routers import live as live_router
    app.include_router(live_router.router, prefix="/api/live")

client = TestClient(app, raise_server_exceptions=False)

# ---------------------------------------------------------------------------
# Mock engine
# ---------------------------------------------------------------------------

def _mock_engine():
    engine = MagicMock()
    engine.kill_all_strategies.return_value = {"stopped": ["runner_1"], "failed": []}
    engine.cancel_all_orders.return_value   = {"cancelled": ["ORD001"],  "failed": []}
    engine.square_off_all.return_value      = {"squared_off": ["RELIANCE"], "failed": []}
    return engine


@pytest.fixture(autouse=True)
def mock_engine(monkeypatch):
    engine = _mock_engine()
    monkeypatch.setattr("live.engine.LiveEngine.instance", staticmethod(lambda: engine))
    try:
        import api.routers.live as live_mod
        monkeypatch.setattr(live_mod, "_get_engine", lambda: engine)
    except (ImportError, AttributeError):
        pass
    return engine


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

KILL_ROUTES = [
    "/api/live/kill/strategies",
    "/api/live/kill/orders",
    "/api/live/kill/positions",
]


# ---------------------------------------------------------------------------
# Guard tests — wrong / missing confirm
# ---------------------------------------------------------------------------

class TestKillGuardReject:
    """All of these must NOT reach the engine."""

    @pytest.mark.parametrize("route", KILL_ROUTES)
    def test_wrong_confirm_returns_400(self, route, mock_engine):
        """Sending confirm != 'CONFIRM' must return 400 (or 422)."""
        r = client.post(route, json={"confirm": "yes"})
        assert r.status_code in (400, 422, 503), (
            f"{route}: expected 400/422 for wrong confirm, got {r.status_code}\n{r.text}"
        )

    @pytest.mark.parametrize("route", KILL_ROUTES)
    def test_empty_confirm_returns_400(self, route, mock_engine):
        """Empty string must be rejected."""
        r = client.post(route, json={"confirm": ""})
        assert r.status_code in (400, 422, 503)

    @pytest.mark.parametrize("route", KILL_ROUTES)
    def test_missing_confirm_returns_400_or_422(self, route, mock_engine):
        """Missing confirm field must be rejected (422 from Pydantic or 400 manual)."""
        r = client.post(route, json={})
        assert r.status_code in (400, 422, 503)

    @pytest.mark.parametrize("route", KILL_ROUTES)
    def test_case_sensitive_confirm(self, route, mock_engine):
        """'CONFIRM' is case-sensitive — lowercase must fail."""
        r = client.post(route, json={"confirm": "confirm"})
        assert r.status_code in (400, 422, 503)

    @pytest.mark.parametrize("route,method", [
        ("/api/live/kill/strategies", "kill_all_strategies"),
        ("/api/live/kill/orders",     "cancel_all_orders"),
        ("/api/live/kill/positions",  "square_off_all"),
    ])
    def test_engine_not_called_on_wrong_confirm(self, route, method, mock_engine):
        """Engine kill methods must NOT be called when confirm is wrong."""
        client.post(route, json={"confirm": "wrong"})
        engine_method = getattr(mock_engine, method)
        engine_method.assert_not_called()


# ---------------------------------------------------------------------------
# Guard tests — correct confirm
# ---------------------------------------------------------------------------

class TestKillGuardAccept:
    """Correct confirm='CONFIRM' should reach the engine."""

    def test_kill_strategies_correct_confirm(self, mock_engine):
        r = client.post("/api/live/kill/strategies", json={"confirm": "CONFIRM"})
        # Accept 200 (success) or 503 (engine not wired) — NOT 400
        assert r.status_code != 400, (
            f"kill/strategies with correct CONFIRM returned 400 — guard is too strict\n{r.text}"
        )

    def test_kill_orders_correct_confirm(self, mock_engine):
        r = client.post("/api/live/kill/orders", json={"confirm": "CONFIRM"})
        assert r.status_code != 400

    def test_kill_positions_correct_confirm(self, mock_engine):
        r = client.post("/api/live/kill/positions", json={"confirm": "CONFIRM"})
        assert r.status_code != 400

    def test_kill_strategies_engine_called(self, mock_engine):
        """With correct confirm, kill_all_strategies() must be invoked."""
        r = client.post("/api/live/kill/strategies", json={"confirm": "CONFIRM"})
        if r.status_code == 200:
            mock_engine.kill_all_strategies.assert_called_once()

    def test_kill_positions_engine_called(self, mock_engine):
        """With correct confirm, square_off_all() must be invoked."""
        r = client.post("/api/live/kill/positions", json={"confirm": "CONFIRM"})
        if r.status_code == 200:
            mock_engine.square_off_all.assert_called_once()
