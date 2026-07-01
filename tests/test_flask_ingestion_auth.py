"""
Tests for ingestion_gateway/flask_ingestion.py — passphrase validation
(Master Task Order 15.3).
"""
import json

import pytest

import flask_ingestion


class _StubRedis:
    def __init__(self):
        self.pushed = []

    def lpush(self, key, value):
        self.pushed.append(value)
        return len(self.pushed)


@pytest.fixture
def client():
    flask_ingestion.app.config["TESTING"] = True
    return flask_ingestion.app.test_client()


def _post(client, payload):
    return client.post(
        "/webhook",
        data=json.dumps(payload),
        content_type="application/json",
    )


def _valid_payload(passphrase):
    return {
        "passphrase": passphrase,
        "strategy_id": "s1",
        "ticker": "AAPL",
        "action": "buy",
    }


def test_rejects_invalid_passphrase(client, monkeypatch):
    monkeypatch.setattr(flask_ingestion, "TV_SECRET", "correct-secret")
    resp = _post(client, _valid_payload("wrong-secret"))
    assert resp.status_code == 401
    assert resp.get_json()["status"] == "unauthorized"


def test_rejects_missing_passphrase_field(client, monkeypatch):
    monkeypatch.setattr(flask_ingestion, "TV_SECRET", "correct-secret")
    payload = _valid_payload("correct-secret")
    del payload["passphrase"]
    resp = _post(client, payload)
    assert resp.status_code == 401
    assert resp.get_json()["status"] == "unauthorized"


def test_rejects_empty_string_passphrase(client, monkeypatch):
    monkeypatch.setattr(flask_ingestion, "TV_SECRET", "correct-secret")
    resp = _post(client, _valid_payload(""))
    assert resp.status_code == 401


def test_passphrase_check_is_case_sensitive(client, monkeypatch):
    monkeypatch.setattr(flask_ingestion, "TV_SECRET", "Correct-Secret")
    resp = _post(client, _valid_payload("correct-secret"))
    assert resp.status_code == 401


def test_accepts_correct_passphrase(client, monkeypatch):
    monkeypatch.setattr(flask_ingestion, "TV_SECRET", "correct-secret")
    monkeypatch.setattr(flask_ingestion, "redis_client", _StubRedis())
    resp = _post(client, _valid_payload("correct-secret"))
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "success"
