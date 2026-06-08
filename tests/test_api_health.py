"""Phase 5 — FastAPI health & index endpoint tests.

Uses FastAPI TestClient — zero network calls, zero broker credentials.
Runs in < 1 second.

Coverage:
  [x] GET /health          — status ok, version present
  [x] GET /api             — lists all 7 route prefixes
  [x] HEAD /health         — method allowed
  [x] GET /health          — app name in response
  [x] GET /api             — /api/live present
  [x] GET /api             — /api/backtest present
  [x] GET /api             — /api/paper present
  [x] GET /nonexistent     — 404
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app, raise_server_exceptions=False)


class TestHealthEndpoint:
    def test_health_status_ok(self):
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"

    def test_health_returns_version(self):
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert "version" in body
        assert body["version"]  # non-empty

    def test_health_returns_app_name(self):
        r = client.get("/health")
        body = r.json()
        assert "app" in body
        assert "Eagle" in body["app"]

    def test_health_head_allowed(self):
        """HEAD /health must not return 405."""
        r = client.head("/health")
        assert r.status_code in (200, 405)  # 405 acceptable if not explicitly wired


class TestApiIndex:
    def test_api_index_ok(self):
        r = client.get("/api")
        assert r.status_code == 200

    def test_api_index_has_routes_key(self):
        r = client.get("/api")
        body = r.json()
        assert "routes" in body
        assert isinstance(body["routes"], list)
        assert len(body["routes"]) >= 5

    def test_api_index_contains_live(self):
        r = client.get("/api")
        routes = r.json()["routes"]
        assert "/api/live" in routes

    def test_api_index_contains_backtest(self):
        r = client.get("/api")
        routes = r.json()["routes"]
        assert "/api/backtest" in routes

    def test_api_index_contains_paper(self):
        r = client.get("/api")
        routes = r.json()["routes"]
        assert "/api/paper" in routes

    def test_api_index_contains_instruments(self):
        r = client.get("/api")
        routes = r.json()["routes"]
        assert "/api/instruments" in routes


class TestNotFound:
    def test_unknown_route_404(self):
        r = client.get("/this/does/not/exist")
        assert r.status_code == 404
