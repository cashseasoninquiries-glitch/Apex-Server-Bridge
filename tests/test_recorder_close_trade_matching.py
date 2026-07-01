"""
Tests for recorder/recorder.py — close_trade() ticker-matching (Master Task Order 15.10).
"""
import pytest

import recorder


class _StubCursor:
    def __init__(self, fetchone_return=None):
        self.executed = []
        self._fetchone_return = fetchone_return

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return self._fetchone_return


def _signal(ticker="AAPL", **extra):
    return {"ticker": ticker, "action": "SELL", **extra}


def test_close_trade_queries_by_strategy_and_ticker_open_status():
    cur = _StubCursor(fetchone_return=("trade-uuid-1", 100.0, 1))
    recorder.close_trade(cur, "strategy-uuid-1", _signal(ticker="AAPL", fill_price=105.0), "event-uuid-1")
    select_query, select_params = cur.executed[0]
    assert "WHERE strategy_id = %s AND ticker = %s AND status = 'open'" in select_query
    assert select_params == ("strategy-uuid-1", "AAPL")


def test_close_trade_orders_by_entry_at_desc_limit_one():
    cur = _StubCursor(fetchone_return=("trade-uuid-1", 100.0, 1))
    recorder.close_trade(cur, "strategy-uuid-1", _signal(), "event-uuid-1")
    select_query, _ = cur.executed[0]
    assert "ORDER BY entry_at DESC" in select_query
    assert "LIMIT 1" in select_query


def test_close_trade_returns_none_when_no_open_trade_found():
    cur = _StubCursor(fetchone_return=None)
    result = recorder.close_trade(cur, "strategy-uuid-1", _signal(), "event-uuid-1")
    assert result is None
    assert len(cur.executed) == 1


def test_close_trade_returns_strategy_id_on_success():
    cur = _StubCursor(fetchone_return=("trade-uuid-1", 100.0, 1))
    result = recorder.close_trade(cur, "strategy-uuid-1", _signal(fill_price=105.0), "event-uuid-1")
    assert result == "strategy-uuid-1"


def test_close_trade_updates_the_matched_trade_id():
    cur = _StubCursor(fetchone_return=("trade-uuid-42", 100.0, 1))
    recorder.close_trade(cur, "strategy-uuid-1", _signal(fill_price=105.0), "event-uuid-1")
    update_query, update_params = cur.executed[1]
    assert "UPDATE trades SET" in update_query
    assert update_params[-1] == "trade-uuid-42"


def test_close_trade_only_matches_open_trades_for_the_given_strategy_and_ticker():
    cur = _StubCursor(fetchone_return=("trade-uuid-1", 50.0, 2))
    recorder.close_trade(cur, "strategy-uuid-7", _signal(ticker="TSLA", fill_price=60.0), "event-uuid-1")
    _, select_params = cur.executed[0]
    assert select_params == ("strategy-uuid-7", "TSLA")
