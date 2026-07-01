"""
Tests for flask_ingestion.py — error notification to apex_notify_queue
(Master Task Order 16.3).

When the outer except fires in tradingview_webhook(), it must push a
dead_letter notification to apex_notify_queue so Discord can surface
gateway failures. The inner try/except around the push means a secondary
Redis failure must NOT mask the original error or crash the process.
"""
import json
import pytest

import flask_ingestion


class _SelectiveFailRedis:
    """Raises on lpush to the signal queue; records lpush to the notify queue."""

    def __init__(self):
        self.pushed = []

    def lpush(self, key, value):
        if key == "apex_signal_queue":
            raise RuntimeError("simulated signal-queue Redis failure")
        self.pushed.append((key, value))


class _AlwaysFailRedis:
    def lpush(self, key, value):
        raise RuntimeError("total Redis outage")


@pytest.fixture
def app():
    flask_ingestion.app.config["TESTING"] = True
    return flask_ingestion.app


def test_outer_except_pushes_dead_letter_to_notify_queue(app, monkeypatch):
    stub = _SelectiveFailRedis()
    monkeypatch.setattr(flask_ingestion, "redis_client", stub)

    with app.test_client() as client:
        resp = client.post(
            "/webhook",
            json={
                "passphrase": flask_ingestion.TV_SECRET,
                "strategy_id": "s1",
                "ticker": "AAPL",
                "action": "LONG",
            },
        )

    assert resp.status_code == 500
    assert len(stub.pushed) == 1
    key, raw = stub.pushed[0]
    assert key == "apex_notify_queue"
    notification = json.loads(raw)
    assert notification["type"] == "dead_letter"
    assert notification["source"] == "flask_ingestion"
    assert "error" in notification
    assert "simulated signal-queue Redis failure" in notification["error"]


def test_notify_push_failure_does_not_raise(app, monkeypatch):
    """When even the notify push fails, the 500 still comes back cleanly —
    no uncaught exception escaping the handler."""
    monkeypatch.setattr(flask_ingestion, "redis_client", _AlwaysFailRedis())

    with app.test_client() as client:
        resp = client.post(
            "/webhook",
            json={
                "passphrase": flask_ingestion.TV_SECRET,
                "strategy_id": "s1",
                "ticker": "AAPL",
                "action": "LONG",
            },
        )

    assert resp.status_code == 500
