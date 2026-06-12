from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


EventsPath = Path("data/events.json")


@dataclass
class Event:
    id: str
    ts: float
    level: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeState:
    running: bool = False
    scan_in_progress: bool = False
    active_task_id: Optional[str] = None
    active_task_name: str = ""
    active_task_config: Optional[dict[str, Any]] = None
    started_at: Optional[float] = None
    last_scan_at: Optional[float] = None
    next_scan_at: Optional[float] = None
    last_error: str = ""
    cycles: int = 0
    recent_offers: list[dict[str, Any]] = field(default_factory=list)
    created_instances: list[dict[str, Any]] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)


class StateStore:
    def __init__(self, events_path: Path = EventsPath, max_events: int = 250):
        self._events_path = events_path
        self._max_events = max_events
        self._lock = threading.RLock()
        self._state = RuntimeState(events=self._load_events())

    def snapshot(self) -> RuntimeState:
        with self._lock:
            return RuntimeState(
                running=self._state.running,
                scan_in_progress=self._state.scan_in_progress,
                active_task_id=self._state.active_task_id,
                active_task_name=self._state.active_task_name,
                active_task_config=self._state.active_task_config,
                started_at=self._state.started_at,
                last_scan_at=self._state.last_scan_at,
                next_scan_at=self._state.next_scan_at,
                last_error=self._state.last_error,
                cycles=self._state.cycles,
                recent_offers=list(self._state.recent_offers),
                created_instances=list(self._state.created_instances),
                events=list(self._state.events),
            )

    def as_dict(self) -> dict[str, Any]:
        state = self.snapshot()
        raw = asdict(state)
        raw["events"] = [asdict(event) for event in state.events]
        return raw

    def update(self, **kwargs) -> None:
        with self._lock:
            for key, value in kwargs.items():
                if not hasattr(self._state, key):
                    raise AttributeError(f"Unknown state field: {key}")
                setattr(self._state, key, value)

    def add_event(self, level: str, message: str, data: Optional[dict[str, Any]] = None) -> Event:
        event = Event(
            id=str(time.time_ns()),
            ts=time.time(),
            level=level,
            message=message,
            data={} if data is None else data,
        )
        with self._lock:
            self._state.events.insert(0, event)
            del self._state.events[self._max_events :]
            self._persist_events_locked()
        return event

    def clear_events(self) -> None:
        with self._lock:
            self._state.events = []
            self._persist_events_locked()

    def set_recent_offers(self, offers: list[dict[str, Any]]) -> None:
        with self._lock:
            self._state.recent_offers = offers

    def add_created_instance(self, item: dict[str, Any]) -> None:
        with self._lock:
            self._state.created_instances.insert(0, item)
            del self._state.created_instances[100:]

    def update_created_instance(self, instance_id: int | str, item: dict[str, Any]) -> None:
        with self._lock:
            for index, existing in enumerate(self._state.created_instances):
                if existing.get("instance_id") == instance_id:
                    self._state.created_instances[index] = item
                    return
            self._state.created_instances.insert(0, item)
            del self._state.created_instances[100:]

    def _load_events(self) -> list[Event]:
        if not self._events_path.exists():
            return []
        with self._events_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        if not isinstance(raw, list):
            raise ValueError("data/events.json must contain an array")
        return [
            Event(
                id=str(item["id"]),
                ts=float(item["ts"]),
                level=str(item["level"]),
                message=str(item["message"]),
                data=dict(item["data"]),
            )
            for item in raw
        ]

    def _persist_events_locked(self) -> None:
        self._events_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._events_path.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump([asdict(event) for event in self._state.events], handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        temp_path.replace(self._events_path)
