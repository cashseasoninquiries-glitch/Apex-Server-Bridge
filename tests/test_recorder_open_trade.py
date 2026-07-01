"""
Tests for recorder/recorder.py — open_trade() (Master Task Order 15.9).
"""
import pytest

import recorder


class _StubCursor:
    def __init__(self):
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((query, params))


@pytest.fixture
def cur():
    return _StubCursor()


def _signal(ticker="AAPL", **extra):
    return {"ticker": ticker, "action": "LONG", **extra}


def test_open_trade_inserts_with_direction_long(cur):
    recorder.open_trade(cur, "strategy-uuid-1", _signal(), "event-uuid-1")
    assert len(cur.executed) == 1
    query, params = cur.executed[0]
    assert "INSERT INTO trades" in query
    assert "'LONG'" in query


def test_open_trade_uses_fill_price_when_present(cur):
    recorder.open_trade(
        cur, "strategy-uuid-1",
        _signal(fill_price=101.5, signal_price=100.0),
        "event-uuid-1",
    )
    _, params = cur.executed[0]
    entry_price = params[3]
    assert entry_price == 101.5


def test_open_trade_falls_back_to_signal_price_when_no_fill_price(cur):
    recorder.open_trade(
        cur, "strategy-uuid-1",
        _signal(signal_price=100.0),
        "event-uuid-1",
    )
    _, params = cur.executed[0]
    entry_price = params[3]
    assert entry_price == 100.0


def test_open_trade_falls_back_to_signal_price_when_fill_price_is_none(cur):
    recorder.open_trade(
        cur, "strategy-uuid-1",
        _signal(fill_price=None, signal_price=99.75),
        "event-uuid-1",
    )
    _, params = cur.executed[0]
    entry_price = params[3]
    assert entry_price == 99.75


def test_open_trade_passes_through_ticker_qty_order_id_and_regime(cur):
    recorder.open_trade(
        cur, "strategy-uuid-1",
        _signal(ticker="MSFT", qty=5, order_id="order-abc", regime="bull", is_paper=False),
        "event-uuid-1",
    )
    _, params = cur.executed[0]
    strategy_id, ticker, event_id, entry_price, qty, order_id, regime, is_paper = params
    assert strategy_id == "strategy-uuid-1"
    assert ticker == "MSFT"
    assert event_id == "event-uuid-1"
    assert qty == 5
    assert order_id == "order-abc"
    assert regime == "bull"
    assert is_paper is False


def test_open_trade_defaults_qty_to_one_and_is_paper_to_true(cur):
    recorder.open_trade(cur, "strategy-uuid-1", _signal(), "event-uuid-1")
    _, params = cur.executed[0]
    qty = params[4]
    is_paper = params[7]
    assert qty == 1
    assert is_paper is True
