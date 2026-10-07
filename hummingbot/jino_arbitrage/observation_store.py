import json
import os
import tempfile
import fcntl
from collections import deque
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List


def _json_default(value: Any):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (tuple, set)):
        return list(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw=json.dumps(payload,default=_json_default,separators=(',',':'),allow_nan=False)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as stream:
        tmp=Path(stream.name)
        try:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        except Exception:
            tmp.unlink(missing_ok=True);raise
    try:os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)


def persist_observation_snapshot(
    log_path: str,
    latest_path: str,
    snapshot: Dict[str, Any],
    max_log_bytes: int = 25_000_000,
) -> None:
    """Persist one read-only observation and atomically refresh the latest snapshot."""
    log = Path(log_path)
    latest = Path(latest_path)
    log.parent.mkdir(parents=True, exist_ok=True)

    if not isinstance(snapshot,dict):raise ValueError('Snapshot must be an object')
    line=json.dumps(snapshot,default=_json_default,separators=(',',':'),allow_nan=False)
    with log.with_suffix(log.suffix+'.lock').open('a') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        if log.exists() and log.stat().st_size>=max_log_bytes:
            rotated=log.with_suffix(log.suffix+'.1')
            rotated.unlink(missing_ok=True);log.replace(rotated)
        with log.open('a',encoding='utf-8') as handle:
            handle.write(line+'\n')
        _atomic_write_json(latest,snapshot)


def read_latest_observation(path: str) -> Dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {}
    data=json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data,dict):raise ValueError('Snapshot must be an object')
    return data


def read_observation_history(path: str, limit: int = 200) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 5000))
    target = Path(path)
    if not target.exists():
        return []

    # The file is intentionally line-oriented so a partially written final line can be skipped.
    rows=deque(maxlen=limit)
    with target.open("r", encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            try:
                row=json.loads(raw)
                if isinstance(row,dict):rows.append(row)
            except json.JSONDecodeError:
                continue
    return list(rows)


def summarize_observations(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = [r for r in records if isinstance(r,dict)]
    profitable = 0
    opportunity_count = 0
    best_profit = None
    best = None

    for row in rows:
        for opportunity in row.get("opportunities") or []:
            if not isinstance(opportunity,dict):continue
            opportunity_count += 1
            try:
                value = Decimal(str(opportunity.get("expected_profit_after_rebalance_quote", "0")))
                if not value.is_finite():continue
            except Exception:
                value = Decimal("0")
            if value > 0:
                profitable += 1
            if best_profit is None or value > best_profit:
                best_profit = value
                best = opportunity

    return {
        "samples": len(rows),
        "opportunities": opportunity_count,
        "profitable_opportunities": profitable,
        "best_expected_profit_after_rebalance_quote": None if best_profit is None else str(best_profit),
        "best_opportunity": best,
        "first_timestamp": rows[0].get("timestamp") if rows else None,
        "last_timestamp": rows[-1].get("timestamp") if rows else None,
    }
