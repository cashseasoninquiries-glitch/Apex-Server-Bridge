"""
Tests for ingestion_gateway/flask_ingestion.py — successful enqueue
(Master Task Order 15.5).

Auth rejection is covered in test_flask_ingestion_auth.py.
test_flask_ingestion_dead_letters.py is now a deletion regression guard
(write_dead_letter/get_db_conn were removed in commit 858d212 to avoid
persisting secret material to Postgres).
"""
import json

import pytest

import flask_ingestion


class _StubRedis:
    def __init__(self):
        self.pushed = []

    def lpush(self, key, value):
        self.pushed.append((key, value))
        return len(self.pushed)


@pytest.fixture
def client():
    flask_ingestion.app.config["TESTING"] = True
    return flask_ingestion.app.test_client()


@pytest.fixture
def stub_redis(monkeypatch):
    stub = _StubRedis()
    monkeypatch.setattr(flask_ingestion, "redis_client", stub)
    return stub


def _post(client, payload):
    return client.post(
        "/webhook",
        data=json.dumps(payload),
        content_type="application/json",
    )


def test_enqueues_to_correct_queue_name(client, stub_redis, monkeypatch):
    monkeypatch.setattr(flask_ingestion, "TV_SECRET", "correct-secret")
    _post(client, {
        "passphrase": "correct-secret",
        "strategy_id": "s1",
        "ticker": "AAPL",
        "action": "buy",
    })
    assert len(stub_redis.pushed) == 1
    queue_name, _ = stub_redis.pushed[0]
    assert queue_name == "apex_signal_queue" == flask_ingestion.QUEUE_NAME


def test_enqueued_payload_strips_passphrase_but_keeps_routing_fields(client, stub_redis, monkeypatch):
    monkeypatch.setattr(flask_ingestion, "TV_SECRET", "correct-secret")
    _post(client, {
        "passphrase": "correct-secret",
        "strategy_id": "s1",
        "ticker": "AAPL",
        "action": "buy",
    })
    _, raw_value = stub_redis.pushed[0]
    queued = json.loads(raw_value)
    assert "passphrase" not in queued
    assert queued["strategy_id"] == "s1"
    assert queued["ticker"] == "AAPL"
    assert queued["action"] == "buy"


def test_enqueued_payload_preserves_extra_fields(client, stub_redis, monkeypatch):
    monkeypatch.setattr(flask_ingestion, "TV_SECRET", "correct-secret")
    _post(client, {
        "passphrase": "correct-secret",
        "strategy_id": "s1",
        "ticker": "AAPL",
        "action": "buy",
        "qty": 10,
        "stop_loss": 150.25,
    })
    _, raw_value = stub_redis.pushed[0]
    queued = json.loads(raw_value)
    assert queued["qty"] == 10
    assert queued["stop_loss"] == 150.25


def test_successful_response_shape(client, stub_redis, monkeypatch):
    monkeypatch.setattr(flask_ingestion, "TV_SECRET", "correct-secret")
    resp = _post(client, {
        "passphrase": "correct-secret",
        "strategy_id": "s1",
        "ticker": "AAPL",
        "action": "buy",
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert "message" in body


def test_each_request_pushes_exactly_once(client, stub_redis, monkeypatch):
    monkeypatch.setattr(flask_ingestion, "TV_SECRET", "correct-secret")
    for _ in range(3):
        _post(client, {
            "passphrase": "correct-secret",
            "strategy_id": "s1",
            "ticker": "AAPL",
            "action": "buy",
        })
    assert len(stub_redis.pushed) == 3
