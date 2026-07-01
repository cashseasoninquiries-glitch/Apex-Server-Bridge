"""
Tests for execution_engine.py — unknown action handling (Master Task Order 15.7).
"""
import json

import pytest

import execution_engine


class _StubRedis:
    def __init__(self):
        self.lrem_calls = []
        self.lpush_calls = []

    def lrem(self, key, count, value):
        self.lrem_calls.append((key, count, value))
        return 1

    def lpush(self, key, value):
        self.lpush_calls.append((key, value))
        return len(self.lpush_calls)


@pytest.fixture
def stub_redis(monkeypatch):
    stub = _StubRedis()
    monkeypatch.setattr(execution_engine, "redis_client", stub)
    return stub


@pytest.fixture(autouse=True)
def allow_position(monkeypatch):
    monkeypatch.setattr(execution_engine, "check_position", lambda *a, **k: (True, "ok"))


@pytest.fixture
def dead_letter_spy(monkeypatch):
    calls = []
    monkeypatch.setattr(execution_engine, "write_dead_letter", lambda payload, error: calls.append((payload, error)))
    return calls


@pytest.fixture
def order_placed_spy(monkeypatch):
    calls = []
    monkeypatch.setattr(execution_engine, "place_order", lambda *a, **k: calls.append((a, k)))
    return calls


def _raw(payload):
    return json.dumps(payload).encode("utf-8")


def test_unknown_action_writes_dead_letter(stub_redis, dead_letter_spy, order_placed_spy):
    execution_engine.process_signal(_raw({
        "strategy_id": "s1", "ticker": "AAPL", "action": "HOLD",
    }))
    assert len(dead_letter_spy) == 1
    payload, error = dead_letter_spy[0]
    assert payload["action"] == "HOLD"
    assert "Unknown action" in error
    assert "HOLD" in error


def test_unknown_action_never_places_an_order(stub_redis, dead_letter_spy, order_placed_spy):
    execution_engine.process_signal(_raw({
        "strategy_id": "s1", "ticker": "AAPL", "action": "CLOSE_ALL",
    }))
    assert order_placed_spy == []


def test_unknown_action_still_acknowledges_buffer(stub_redis, dead_letter_spy, order_placed_spy):
    execution_engine.process_signal(_raw({
        "strategy_id": "s1", "ticker": "AAPL", "action": "FOO",
    }))
    assert len(stub_redis.lrem_calls) == 1
    key, count, _ = stub_redis.lrem_calls[0]
    assert key == execution_engine.BUFFER_NAME
    assert count == 1


def test_unknown_action_does_not_push_to_record_queue(stub_redis, dead_letter_spy, order_placed_spy):
    execution_engine.process_signal(_raw({
        "strategy_id": "s1", "ticker": "AAPL", "action": "FOO",
    }))
    assert stub_redis.lpush_calls == []
