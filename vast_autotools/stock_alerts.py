from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .config import AppConfig, config_to_dict


StockAlertsPath = Path("data/stock_alerts.json")


@dataclass
class StockAlertDecision:
    task_key: str
    filter_hash: str
    current_count: int
    baseline_count: Optional[int]
    drop_count: int
    drop_percent: float
    sample_count: int
    should_alert: bool
    reason: str
    cooled_down: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_key": self.task_key,
            "filter_hash": self.filter_hash,
            "current_count": self.current_count,
            "baseline_count": self.baseline_count,
            "drop_count": self.drop_count,
            "drop_percent": self.drop_percent,
            "sample_count": self.sample_count,
            "should_alert": self.should_alert,
            "reason": self.reason,
            "cooled_down": self.cooled_down,
        }


class StockAlertStore:
    def __init__(self, path: Path = StockAlertsPath):
        self._path = path

    def record_scan(self, config: AppConfig, task_id: Optional[str], count: int, now: Optional[float] = None) -> StockAlertDecision:
        if now is None:
            now = time.time()
        task_key = _task_key(task_id)
        filter_hash = filter_hash_for_config(config)
        rows = self._load()
        key = _storage_key(task_key, filter_hash)
        row = rows.get(key)
        if row is None:
            row = {"task_key": task_key, "filter_hash": filter_hash, "samples": [], "last_alert_at": None}

        window_seconds = config.monitor.stock_alert_window_minutes * 60
        since = now - window_seconds
        samples = _samples_in_window(row["samples"], since)
        baseline_count = max(sample["count"] for sample in samples) if samples else None
        decision = _decide(config, task_key, filter_hash, count, samples, baseline_count, row["last_alert_at"], now)

        samples.append({"ts": now, "count": count})
        row["samples"] = _samples_in_window(samples, since)
        if decision.should_alert:
            row["last_alert_at"] = now
        row["task_key"] = task_key
        row["filter_hash"] = filter_hash
        rows[key] = row
        self._save(rows)
        return decision

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        with self._path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        if not isinstance(raw, dict):
            raise ValueError("data/stock_alerts.json must contain an object")
        rows: dict[str, dict[str, Any]] = {}
        for key, item in raw.items():
            if not isinstance(key, str) or not isinstance(item, dict):
                raise ValueError("stock alert rows must be keyed objects")
            rows[key] = _parse_row(item)
        return rows

    def _save(self, rows: dict[str, dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(rows, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        temp_path.replace(self._path)


def filter_hash_for_config(config: AppConfig) -> str:
    raw = config_to_dict(config)
    signature = {
        "platform": raw["platform"],
        "search": raw["search"],
    }
    data = json.dumps(signature, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]


def _decide(
    config: AppConfig,
    task_key: str,
    filter_hash: str,
    count: int,
    samples: list[dict[str, Any]],
    baseline_count: Optional[int],
    last_alert_at: Any,
    now: float,
) -> StockAlertDecision:
    if not config.monitor.stock_alert_enabled:
        return StockAlertDecision(task_key, filter_hash, count, baseline_count, 0, 0.0, len(samples), False, "disabled", False)
    if baseline_count is None:
        return StockAlertDecision(task_key, filter_hash, count, None, 0, 0.0, len(samples), False, "warming_up", False)
    if baseline_count < config.monitor.stock_alert_min_baseline_count:
        return StockAlertDecision(task_key, filter_hash, count, baseline_count, 0, 0.0, len(samples), False, "baseline_too_low", False)

    drop_count = baseline_count - count
    drop_percent = (drop_count / baseline_count) * 100.0
    meets_drop_count = drop_count >= config.monitor.stock_alert_drop_count
    meets_drop_percent = drop_percent >= config.monitor.stock_alert_drop_percent
    cooled_down = _cooldown_elapsed(last_alert_at, config.monitor.stock_alert_cooldown_minutes, now)
    should_alert = meets_drop_count and meets_drop_percent and cooled_down
    if should_alert:
        reason = "stock_drop"
    elif meets_drop_count and meets_drop_percent:
        reason = "cooldown"
    else:
        reason = "drop_below_threshold"
    return StockAlertDecision(
        task_key=task_key,
        filter_hash=filter_hash,
        current_count=count,
        baseline_count=baseline_count,
        drop_count=drop_count,
        drop_percent=drop_percent,
        sample_count=len(samples),
        should_alert=should_alert,
        reason=reason,
        cooled_down=cooled_down,
    )


def _parse_row(item: dict[str, Any]) -> dict[str, Any]:
    task_key = item.get("task_key")
    filter_hash = item.get("filter_hash")
    if not isinstance(task_key, str) or not task_key:
        raise ValueError("stock alert task_key must be a non-empty string")
    if not isinstance(filter_hash, str) or not filter_hash:
        raise ValueError("stock alert filter_hash must be a non-empty string")
    samples = item.get("samples")
    if not isinstance(samples, list):
        raise ValueError("stock alert samples must be an array")
    last_alert_at = item.get("last_alert_at")
    if last_alert_at is not None and not isinstance(last_alert_at, (int, float)):
        raise ValueError("stock alert last_alert_at must be a number or null")
    return {
        "task_key": task_key,
        "filter_hash": filter_hash,
        "samples": [_parse_sample(sample) for sample in samples],
        "last_alert_at": None if last_alert_at is None else float(last_alert_at),
    }


def _parse_sample(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("stock alert samples must contain objects")
    ts = item.get("ts")
    count = item.get("count")
    if not isinstance(ts, (int, float)) or isinstance(ts, bool):
        raise ValueError("stock alert sample ts must be a number")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise ValueError("stock alert sample count must be a non-negative integer")
    return {"ts": float(ts), "count": count}


def _samples_in_window(samples: list[dict[str, Any]], since: float) -> list[dict[str, Any]]:
    return [sample for sample in samples if sample["ts"] >= since]


def _cooldown_elapsed(last_alert_at: Any, cooldown_minutes: int, now: float) -> bool:
    if last_alert_at is None:
        return True
    if not isinstance(last_alert_at, (int, float)) or isinstance(last_alert_at, bool):
        raise ValueError("stock alert last_alert_at must be a number or null")
    return now - float(last_alert_at) >= cooldown_minutes * 60


def _task_key(task_id: Optional[str]) -> str:
    if task_id is None:
        return "manual"
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id must be a non-empty string")
    return task_id.strip()


def _storage_key(task_key: str, filter_hash: str) -> str:
    return f"{task_key}:{filter_hash}"
