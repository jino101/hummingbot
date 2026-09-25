import json
from decimal import Decimal

from hummingbot.jino_arbitrage.observation_store import (
    persist_observation_snapshot,
    read_latest_observation,
    read_observation_history,
    summarize_observations,
)


def test_persist_read_and_summarize_observations(tmp_path):
    log = tmp_path / "history.jsonl"
    latest = tmp_path / "latest.json"

    first = {
        "timestamp": 1,
        "mode": "observe",
        "opportunities": [
            {
                "trading_pair": "BTC-USDT",
                "expected_profit_after_rebalance_quote": "0.12",
            }
        ],
    }
    second = {
        "timestamp": 2,
        "mode": "observe",
        "opportunities": [
            {
                "trading_pair": "BTC-USDT",
                "expected_profit_after_rebalance_quote": "-0.01",
            }
        ],
    }

    persist_observation_snapshot(str(log), str(latest), first)
    persist_observation_snapshot(str(log), str(latest), second)

    assert read_latest_observation(str(latest)) == second
    rows = read_observation_history(str(log), limit=10)
    assert rows == [first, second]

    summary = summarize_observations(rows)
    assert summary["samples"] == 2
    assert summary["opportunities"] == 2
    assert summary["profitable_opportunities"] == 1
    assert summary["best_expected_profit_after_rebalance_quote"] == "0.12"


def test_decimal_values_are_serialized(tmp_path):
    log = tmp_path / "history.jsonl"
    latest = tmp_path / "latest.json"
    persist_observation_snapshot(
        str(log),
        str(latest),
        {"timestamp": 1, "value": Decimal("1.23"), "opportunities": []},
    )
    payload = json.loads(latest.read_text())
    assert payload["value"] == "1.23"


def test_corrupt_history_line_is_ignored(tmp_path):
    log = tmp_path / "history.jsonl"
    log.write_text('{"timestamp":1,"opportunities":[]}\n{broken\n', encoding="utf-8")
    rows = read_observation_history(str(log))
    assert len(rows) == 1
    assert rows[0]["timestamp"] == 1
