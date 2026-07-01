"""
Tests for execution_engine.py — action routing (Master Task Order 15.6).
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
def allow_position(monkeypatch):
    monkeypatch.setattr(execution_engine, "check_position", lambda *a, **k: (True, "ok"))


@pytest.fixture
def fake_order(monkeypatch):
    order = SimpleNamespace(id="order-123")
    monkeypatch.setattr(execution_engine, "wait_for_fill", lambda order_id: 101.5)
    return order


def _patch_place_order(monkeypatch, order):
    captured = {}

    def fake_place_order(symbol, side):
        captured["symbol"] = symbol
        captured["side"] = side
        return order

    monkeypatch.setattr(execution_engine, "place_order", fake_place_order)
    return captured


def _raw(payload):
    return json.dumps(payload).encode("utf-8")


def _signal(action="LONG", ticker="AAPL", strategy_id="s1", **extra):
    return {"strategy_id": strategy_id, "ticker": ticker, "action": action, **extra}


def test_long_routes_to_buy(stub_redis, fake_order, monkeypatch):
    captured = _patch_place_order(monkeypatch, fake_order)
    execution_engine.process_signal(_raw(_signal(action="LONG", ticker="AAPL")))
    assert captured["symbol"] == "AAPL"
    assert captured["side"] == execution_engine.OrderSide.BUY


def test_sell_routes_to_sell(stub_redis, fake_order, monkeypatch):
    captured = _patch_place_order(monkeypatch, fake_order)
    execution_engine.process_signal(_raw(_signal(action="SELL")))
    assert captured["side"] == execution_engine.OrderSide.SELL


def test_short_routes_to_sell_same_as_sell(stub_redis, fake_order, monkeypatch):
    captured = _patch_place_order(monkeypatch, fake_order)
    execution_engine.process_signal(_raw(_signal(action="SHORT")))
    assert captured["side"] == execution_engine.OrderSide.SELL


def test_action_routing_is_case_insensitive(stub_redis, fake_order, monkeypatch):
    captured = _patch_place_order(monkeypatch, fake_order)
    execution_engine.process_signal(_raw(_signal(action="long")))
    assert captured["side"] == execution_engine.OrderSide.BUY


def test_position_gate_block_prevents_order_placement(stub_redis, monkeypatch):
    monkeypatch.setattr(execution_engine, "check_position", lambda *a, **k: (False, "Blocked: already open"))
    order_attempts = []
    monkeypatch.setattr(execution_engine, "place_order", lambda *a, **k: order_attempts.append((a, k)))
    execution_engine.process_signal(_raw(_signal(action="LONG")))
    assert order_attempts == []
    assert len(stub_redis.lrem_calls) == 1


def test_missing_ticker_or_action_skips_routing_entirely(stub_redis, monkeypatch):
    order_attempts = []
    monkeypatch.setattr(execution_engine, "place_order", lambda *a, **k: order_attempts.append((a, k)))
    monkeypatch.setattr(execution_engine, "write_dead_letter", lambda *a, **k: None)
    execution_engine.process_signal(_raw({"strategy_id": "s1", "ticker": "", "action": ""}))
    assert order_attempts == []
    assert len(stub_redis.lrem_calls) == 1
