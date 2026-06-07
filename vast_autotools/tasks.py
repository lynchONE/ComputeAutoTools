from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from .config import AppConfig, config_from_dict, config_to_dict


TasksPath = Path("data/tasks.json")


@dataclass
class MonitorTask:
    id: str
    name: str
    config: dict[str, Any]
    created_at: float
    updated_at: float
    status: str = "stopped"
    last_started_at: Optional[float] = None
    last_stopped_at: Optional[float] = None
    last_scan_at: Optional[float] = None
    next_scan_at: Optional[float] = None
    cycles: int = 0
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TaskStore:
    def __init__(self, path: Path = TasksPath):
        self._path = path

    def list_tasks(self) -> list[dict[str, Any]]:
        return [task.to_dict() for task in self._load()]

    def get_task(self, task_id: str) -> MonitorTask:
        for task in self._load():
            if task.id == task_id:
                return task
        raise KeyError(f"monitor task not found: {task_id}")

    def create_task(self, name: str, config: AppConfig, task_id: Optional[str] = None) -> MonitorTask:
        clean_name = _clean_name(name)
        tasks = self._load()
        new_id = _clean_id(task_id) if task_id is not None else f"task-{time.time_ns()}"
        if any(task.id == new_id for task in tasks):
            raise ValueError(f"monitor task already exists: {new_id}")
        now = time.time()
        task = MonitorTask(
            id=new_id,
            name=clean_name,
            config=config_to_dict(config),
            created_at=now,
            updated_at=now,
        )
        tasks.append(task)
        self._save(tasks)
        return task

    def upsert_task(self, task_id: str, name: str, config: AppConfig) -> MonitorTask:
        clean_id = _clean_id(task_id)
        clean_name = _clean_name(name)
        tasks = self._load()
        now = time.time()
        for index, task in enumerate(tasks):
            if task.id != clean_id:
                continue
            task.name = clean_name
            task.config = config_to_dict(config)
            task.updated_at = now
            tasks[index] = task
            self._save(tasks)
            return task
        task = MonitorTask(
            id=clean_id,
            name=clean_name,
            config=config_to_dict(config),
            created_at=now,
            updated_at=now,
        )
        tasks.append(task)
        self._save(tasks)
        return task

    def update_task(self, task_id: str, name: str, config: AppConfig) -> MonitorTask:
        clean_id = _clean_id(task_id)
        clean_name = _clean_name(name)
        tasks = self._load()
        for index, task in enumerate(tasks):
            if task.id != clean_id:
                continue
            task.name = clean_name
            task.config = config_to_dict(config)
            task.updated_at = time.time()
            tasks[index] = task
            self._save(tasks)
            return task
        raise KeyError(f"monitor task not found: {clean_id}")

    def delete_task(self, task_id: str) -> MonitorTask:
        clean_id = _clean_id(task_id)
        tasks = self._load()
        for index, task in enumerate(tasks):
            if task.id != clean_id:
                continue
            removed = tasks.pop(index)
            self._save(tasks)
            return removed
        raise KeyError(f"monitor task not found: {clean_id}")

    def update_runtime(self, task_id: str, **kwargs: Any) -> MonitorTask:
        clean_id = _clean_id(task_id)
        allowed = {
            "status",
            "last_started_at",
            "last_stopped_at",
            "last_scan_at",
            "next_scan_at",
            "cycles",
            "last_error",
        }
        extra = set(kwargs) - allowed
        if extra:
            names = ", ".join(sorted(extra))
            raise ValueError(f"unknown runtime fields: {names}")
        tasks = self._load()
        for index, task in enumerate(tasks):
            if task.id != clean_id:
                continue
            for key, value in kwargs.items():
                setattr(task, key, value)
            tasks[index] = task
            self._save(tasks)
            return task
        raise KeyError(f"monitor task not found: {clean_id}")

    def _load(self) -> list[MonitorTask]:
        if not self._path.exists():
            return []
        with self._path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        if not isinstance(raw, list):
            raise ValueError("data/tasks.json must contain an array")
        tasks: list[MonitorTask] = []
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("data/tasks.json task rows must be objects")
            config = config_from_dict(item["config"])
            tasks.append(
                MonitorTask(
                    id=str(item["id"]),
                    name=str(item["name"]),
                    config=config_to_dict(config),
                    created_at=float(item["created_at"]),
                    updated_at=float(item["updated_at"]),
                    status=str(item["status"]),
                    last_started_at=_optional_float(item.get("last_started_at")),
                    last_stopped_at=_optional_float(item.get("last_stopped_at")),
                    last_scan_at=_optional_float(item.get("last_scan_at")),
                    next_scan_at=_optional_float(item.get("next_scan_at")),
                    cycles=_int_field(item.get("cycles"), "cycles"),
                    last_error=str(item.get("last_error") or ""),
                )
            )
        return tasks

    def _save(self, tasks: list[MonitorTask]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump([task.to_dict() for task in tasks], handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        temp_path.replace(self._path)


def _clean_id(task_id: str) -> str:
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id is required")
    clean = task_id.strip()
    if not clean.replace("-", "").replace("_", "").isalnum():
        raise ValueError("task_id may only contain letters, numbers, '-' and '_'")
    return clean


def _clean_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("task name is required")
    return name.strip()


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("task timestamp fields must be numbers or null")
    return float(value)


def _int_field(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"task {name} must be an integer")
    return value
