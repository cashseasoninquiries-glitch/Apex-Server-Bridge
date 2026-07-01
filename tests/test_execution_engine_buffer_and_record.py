"""
Tests for execution_engine.py — buffer acknowledgement (lrem) and the
record-queue handoff (Master Task Order 15.8).
"""
import json
from types import SimpleNamespace

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
def silence_dead_letter(monkeypatch):
    monkeypatch.setattr(execution_engine, "write_dead_letter", lambda *a, **k: None)


def _raw(payload):
    return json.dumps(payload).encode("utf-8")


def _signal(action="LONG", ticker="AAPL", strategy_id="s1", **extra):
    return {"strategy_id": strategy_id, "ticker": ticker, "action": action, **extra}


def test_successful_execution_acks_exact_raw_payload(stub_redis, monkeypatch):
    monkeypatch.setattr(execution_engine, "check_position", lambda *a, **k: (True, "ok"))
    order = SimpleNamespace(id="order-123")
    monkeypatch.setattr(execution_engine, "place_order", lambda *a, **k: order)
    monkeypatch.setattr(execution_engine, "wait_for_fill", lambda order_id: 101.5)
    raw_payload = _raw(_signal())
    execution_engine.process_signal(raw_payload)
    assert len(stub_redis.lrem_calls) == 1
    key, count, value = stub_redis.lrem_calls[0]
    assert key == execution_engine.BUFFER_NAME
    assert count == 1
    assert value == raw_payload


def test_successful_execution_pushes_correctly_shaped_record(stub_redis, monkeypatch):
    monkeypatch.setattr(execution_engine, "check_position", lambda *a, **k: (True, "ok"))
    order = SimpleNamespace(id="order-456")
    monkeypatch.setattr(execution_engine, "place_order", lambda *a, **k: order)
    monkeypatch.setattr(execution_engine, "wait_for_fill", lambda order_id: 188.42)
    execution_engine.process_signal(_raw(_signal(ticker="MSFT", action="LONG", signal_price=187.0)))
    assert len(stub_redis.lpush_calls) == 1
    queue_name, raw_record = stub_redis.lpush_calls[0]
    assert queue_name == execution_engine.RECORD_QUEUE
    record = json.loads(raw_record)
    assert record["order_id"] == "order-456"
    assert record["status"] == "executed"
    assert record["fill_price"] == 188.42
    assert record["is_paper"] == execution_engine.PAPER_TRADING
    assert record["ticker"] == "MSFT"
    assert record["signal_price"] == 187.0


def test_fill_timeout_falls_back_to_none_but_still_records(stub_redis, monkeypatch):
    monkeypatch.setattr(execution_engine, "check_position", lambda *a, **k: (True, "ok"))
    order = SimpleNamespace(id="order-789")
    monkeypatch.setattr(execution_engine, "place_order", lambda *a, **k: order)
    monkeypatch.setattr(execution_engine, "wait_for_fill", lambda order_id: None)
    execution_engine.process_signal(_raw(_signal()))
    _, raw_record = stub_redis.lpush_calls[0]
    record = json.loads(raw_record)
    assert record["fill_price"] is None


@pytest.mark.parametrize("signal_payload", [
    {"strategy_id": "s1", "ticker": "", "action": ""},
    {"strategy_id": "s1", "ticker": "AAPL", "action": "HOLD"},
])
def test_rejected_signals_still_ack_buffer_exactly_once(stub_redis, monkeypatch, signal_payload):
    monkeypatch.setattr(execution_engine, "check_position", lambda *a, **k: (True, "ok"))
    execution_engine.process_signal(_raw(signal_payload))
    assert len(stub_redis.lrem_calls) == 1


def test_position_gate_blocked_signal_acks_buffer_exactly_once_and_no_record(stub_redis, monkeypatch):
    monkeypatch.setattr(execution_engine, "check_position", lambda *a, **k: (False, "blocked"))
    execution_engine.process_signal(_raw(_signal()))
    assert len(stub_redis.lrem_calls) == 1
    assert stub_redis.lpush_calls == []
