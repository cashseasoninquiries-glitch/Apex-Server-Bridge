"""
Tests for recorder/recorder.py — PnL math inside close_trade() (Master Task Order 15.11).

Formulas:
    pnl     = (exit_price - entry_price) * qty
    pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price else 0
    exit_price = float(signal.get('fill_price') or signal.get('signal_price') or 0)
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


def _update_params(cur):
    _, params = cur.executed[1]
    return params  # (event_id, exit_price, pnl, pnl_pct, regime, trade_id)


def test_pnl_on_a_winning_long_close():
    cur = _StubCursor(fetchone_return=("trade-1", 100.0, 10))
    recorder.close_trade(cur, "s1", {"ticker": "AAPL", "fill_price": 110.0}, "event-1")
    _, exit_price, pnl, pnl_pct, _, _ = _update_params(cur)
    assert exit_price == 110.0
    assert pnl == pytest.approx((110.0 - 100.0) * 10)
    assert pnl_pct == pytest.approx((110.0 - 100.0) / 100.0 * 100)


def test_pnl_on_a_losing_long_close():
    cur = _StubCursor(fetchone_return=("trade-1", 100.0, 10))
    recorder.close_trade(cur, "s1", {"ticker": "AAPL", "fill_price": 92.0}, "event-1")
    _, exit_price, pnl, pnl_pct, _, _ = _update_params(cur)
    assert pnl == pytest.approx((92.0 - 100.0) * 10)
    assert pnl_pct == pytest.approx((92.0 - 100.0) / 100.0 * 100)


def test_pnl_pct_is_zero_when_entry_price_is_zero():
    cur = _StubCursor(fetchone_return=("trade-1", 0.0, 10))
    recorder.close_trade(cur, "s1", {"ticker": "AAPL", "fill_price": 50.0}, "event-1")
    _, _, pnl, pnl_pct, _, _ = _update_params(cur)
    assert pnl_pct == 0


def test_exit_price_falls_back_to_signal_price_when_no_fill_price():
    cur = _StubCursor(fetchone_return=("trade-1", 100.0, 1))
    recorder.close_trade(cur, "s1", {"ticker": "AAPL", "signal_price": 95.0}, "event-1")
    _, exit_price, _, _, _, _ = _update_params(cur)
    assert exit_price == 95.0


def test_exit_price_falls_back_to_zero_when_neither_price_present():
    cur = _StubCursor(fetchone_return=("trade-1", 100.0, 1))
    recorder.close_trade(cur, "s1", {"ticker": "AAPL"}, "event-1")
    _, exit_price, _, _, _, _ = _update_params(cur)
    assert exit_price == 0.0


def test_slippage_computation_does_not_crash_when_prices_differ():
    cur = _StubCursor(fetchone_return=("trade-1", 100.0, 1))
    result = recorder.close_trade(
        cur, "s1",
        {"ticker": "AAPL", "fill_price": 110.25, "signal_price": 110.00},
        "event-1",
    )
    assert result == "s1"


def test_pnl_math_uses_quantity_from_the_matched_trade_not_the_signal():
    cur = _StubCursor(fetchone_return=("trade-1", 100.0, 25))
    recorder.close_trade(cur, "s1", {"ticker": "AAPL", "fill_price": 104.0}, "event-1")
    _, _, pnl, _, _, _ = _update_params(cur)
    assert pnl == pytest.approx((104.0 - 100.0) * 25)
