"""
Tests for discord_notifier.py — build_embed() template selection
(Master Task Order 15.13).
"""
import json

import discord_notifier


def test_promoted_green_template():
    embed = discord_notifier.build_embed({
        "type": "promoted_green",
        "strategy_id": "rsi-momentum-v2",
        "sharpe": 1.85,
        "win_rate": 0.62,
        "max_drawdown": 0.08,
        "total_trades": 142,
    })
    body = embed["embeds"][0]
    assert "Promoted" in body["title"]
    assert "Green" in body["title"]
    assert body["color"] == discord_notifier.COLORS["promoted_green"]
    assert "rsi-momentum-v2" in body["description"]
    assert "1.850" in body["description"]
    assert "62.0%" in body["description"]


def test_demoted_red_template():
    embed = discord_notifier.build_embed({
        "type": "demoted_red",
        "strategy_id": "macd-cross-v1",
        "sharpe": -0.4,
        "win_rate": 0.31,
        "max_drawdown": 0.27,
    })
    body = embed["embeds"][0]
    assert "Flagged" in body["title"]
    assert "Red" in body["title"]
    assert body["color"] == discord_notifier.COLORS["demoted_red"]
    assert "macd-cross-v1" in body["description"]
    assert "27.0%" in body["description"]


def test_culled_grey_template():
    embed = discord_notifier.build_embed({
        "type": "culled_grey",
        "strategy_id": "old-strategy-v0",
    })
    body = embed["embeds"][0]
    assert "Auto-Culled" in body["title"]
    assert "Grey" in body["title"]
    assert body["color"] == discord_notifier.COLORS["culled_grey"]
    assert "old-strategy-v0" in body["description"]


def test_perf_update_template_reads_nested_metrics_dict():
    embed = discord_notifier.build_embed({
        "type": "perf_update",
        "strategy_id": "rsi-momentum-v2",
        "metrics": {
            "total_trades": 200,
            "win_rate": 0.55,
            "sharpe_ratio": 1.2,
            "total_pnl": 4321.50,
        },
    })
    body = embed["embeds"][0]
    assert "Performance Updated" in body["title"]
    assert "200" in body["description"]
    assert "55.0%" in body["description"]
    assert "$4321.50" in body["description"]


def test_dead_letter_template_truncates_long_error_messages():
    long_error = "x" * 1000
    embed = discord_notifier.build_embed({
        "type": "dead_letter",
        "source": "execution_engine",
        "error": long_error,
    })
    body = embed["embeds"][0]
    assert "Dead Letter" in body["title"]
    assert "execution_engine" in body["description"]
    assert long_error[:300] in body["description"]
    assert long_error[300:] not in body["description"]


def test_unknown_type_falls_back_to_generic_template():
    embed = discord_notifier.build_embed({
        "type": "some_future_type_nobody_added_a_template_for",
        "strategy_id": "s1",
        "weird_field": 123,
    })
    body = embed["embeds"][0]
    assert "Apex Notification" in body["title"]
    assert body["color"] == 0x7F8C8D
    assert "weird_field" in body["description"]


def test_missing_type_also_falls_back_to_generic_template():
    embed = discord_notifier.build_embed({"strategy_id": "s1"})
    body = embed["embeds"][0]
    assert "Apex Notification" in body["title"]


def test_every_template_includes_a_footer_timestamp():
    for ntype in ("promoted_green", "demoted_red", "culled_grey", "perf_update", "dead_letter", "unknown"):
        embed = discord_notifier.build_embed({"type": ntype, "strategy_id": "s1", "metrics": {}})
        assert "footer" in embed["embeds"][0]
        assert "Apex Engine" in embed["embeds"][0]["footer"]["text"]
