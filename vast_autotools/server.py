from __future__ import annotations

import json
import mimetypes
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import ConfigError, ConfigPath, config_from_dict, config_to_dict, load_config
from .monitor import MonitorService
from .platforms import PlatformNotSupported, build_adapter, platform_fallback_gpu_models, platform_gpu_models
from .state import StateStore
from .vast_adapter import build_order, build_search_query


StaticDir = Path(__file__).resolve().parent.parent / "web"


class AppContext:
    def __init__(self):
        self.state = StateStore()
        self.monitor = MonitorService(self.state)


class RequestHandler(BaseHTTPRequestHandler):
    context: AppContext

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/config":
                self._send_json(config_to_dict(load_config(ConfigPath)))
            elif parsed.path == "/api/state":
                self._send_json(self.context.state.as_dict())
            elif parsed.path == "/api/query":
                config = load_config(ConfigPath)
                if config.platform.provider == "runpod":
                    self._send_json({"query": "RunPod uses GPU type pricing and stockStatus via GraphQL gpuTypes", "order": config.search.order_by})
                    return
                if config.platform.provider != "vast":
                    raise PlatformNotSupported(f"{config.platform.provider} query preview is not implemented yet")
                self._send_json({"query": build_search_query(config.search), "order": build_order(config.search.order_by)})
            elif parsed.path == "/api/gpu-models":
                self._send_json(self._gpu_models_payload())
            elif parsed.path == "/api/tasks":
                self._send_json({"tasks": self.context.monitor.list_tasks()})
            elif parsed.path == "/api/instances":
                config = load_config(ConfigPath)
                self._send_json({"instances": build_adapter(config).list_instances()})
            elif parsed.path == "/api/templates":
                config = load_config(ConfigPath)
                query = parse_qs(parsed.query)
                keyword = query.get("q", [""])[0]
                self._send_json({"templates": build_adapter(config).search_templates(keyword=keyword)})
            elif parsed.path.startswith("/api/"):
                self._send_error(HTTPStatus.NOT_FOUND, "API not found")
            else:
                self._serve_static(parsed.path)
        except Exception as exc:
            self._send_exception(exc)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/scan":
                self._send_json(self.context.monitor.scan_once())
            elif parsed.path == "/api/monitor/start":
                self.context.monitor.start()
                self._send_json({"running": True})
            elif parsed.path == "/api/monitor/stop":
                self.context.monitor.stop()
                self._send_json({"running": False})
            elif parsed.path == "/api/query-preview":
                body = self._read_json()
                config = config_from_dict(body)
                if config.platform.provider == "runpod":
                    self._send_json({"query": "RunPod uses GPU type pricing and stockStatus via GraphQL gpuTypes", "order": config.search.order_by})
                    return
                if config.platform.provider != "vast":
                    raise PlatformNotSupported(f"{config.platform.provider} query preview is not implemented yet")
                self._send_json(
                    {"query": build_search_query(config.search), "order": build_order(config.search.order_by)}
                )
            elif parsed.path == "/api/gpu-models-preview":
                config = config_from_dict(self._read_json())
                self._send_json(self._gpu_models_payload(config))
            elif parsed.path == "/api/templates-preview":
                query = parse_qs(parsed.query)
                keyword = query.get("q", [""])[0]
                config = config_from_dict(self._read_json())
                self._send_json({"templates": build_adapter(config).search_templates(keyword=keyword)})
            elif parsed.path == "/api/tasks":
                body = self._read_json()
                task = self.context.monitor.create_task(_task_name(body), config_from_dict(_task_config(body)))
                self._send_json({"task": task}, status=HTTPStatus.CREATED)
            elif parsed.path.startswith("/api/tasks/") and parsed.path.endswith("/start"):
                task_id = _task_id_from_path(parsed.path, suffix="/start")
                self.context.monitor.start_task(task_id)
                self._send_json({"running": True, "task_id": task_id})
            elif parsed.path.startswith("/api/tasks/") and parsed.path.endswith("/stop"):
                self.context.monitor.stop()
                self._send_json({"running": False})
            elif parsed.path == "/api/create-targets":
                body = self._read_json()
                offer_ids = body.get("target_offer_ids")
                if not isinstance(offer_ids, list):
                    raise ValueError("target_offer_ids must be an array")
                if not all(isinstance(offer_id, int) and not isinstance(offer_id, bool) for offer_id in offer_ids):
                    raise ValueError("target_offer_ids must contain integers")
                config = self.context.monitor.update_target_offer_ids(offer_ids)
                self._send_json({"target_offer_ids": config.create.target_offer_ids})
            elif parsed.path == "/api/test/bark":
                self.context.monitor.send_test_bark()
                self._send_json({"ok": True})
            elif parsed.path == "/api/instances/cleanup-errors":
                self._send_json({"cleaned": self.context.monitor.cleanup_failed_managed_instances()})
            elif parsed.path == "/api/instances/delete":
                body = self._read_json()
                instance_ids = body.get("instance_ids")
                if not isinstance(instance_ids, list):
                    raise ValueError("instance_ids must be an array")
                if not all(
                    (isinstance(instance_id, int) and not isinstance(instance_id, bool))
                    or (isinstance(instance_id, str) and bool(instance_id.strip()))
                    for instance_id in instance_ids
                ):
                    raise ValueError("instance_ids must contain non-empty strings or integers")
                self._send_json({"deleted": self.context.monitor.delete_instances(instance_ids)})
            elif parsed.path.startswith("/api/"):
                self._send_error(HTTPStatus.NOT_FOUND, "API not found")
            else:
                self._send_error(HTTPStatus.NOT_FOUND, "Not found")
        except Exception as exc:
            self._send_exception(exc)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/config":
                body = self._read_json()
                config = config_from_dict(body)
                self.context.monitor.update_config(config)
                self._send_json(config_to_dict(config))
            elif parsed.path.startswith("/api/tasks/"):
                body = self._read_json()
                task_id = _task_id_from_path(parsed.path)
                task = self.context.monitor.update_task(task_id, _task_name(body), config_from_dict(_task_config(body)))
                self._send_json({"task": task})
            elif parsed.path.startswith("/api/"):
                self._send_error(HTTPStatus.NOT_FOUND, "API not found")
            else:
                self._send_error(HTTPStatus.NOT_FOUND, "Not found")
        except Exception as exc:
            self._send_exception(exc)

    def _read_json(self) -> dict[str, Any]:
        length_text = self.headers.get("Content-Length")
        if length_text is None:
            raise ValueError("Missing Content-Length")
        length = int(length_text)
        body = self.rfile.read(length)
        raw = json.loads(body.decode("utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("JSON body must be an object")
        return raw

    def _serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in ("", "/") else request_path.lstrip("/")
        target = (StaticDir / relative).resolve()
        static_root = StaticDir.resolve()
        if not target.is_file() or static_root not in target.parents and target != static_root:
            self._send_error(HTTPStatus.NOT_FOUND, "File not found")
            return

        content_type = mimetypes.guess_type(str(target))[0]
        if content_type is None:
            content_type = "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
            content_type = f"{content_type}; charset=utf-8"
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, socket.timeout):
            return

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/api/tasks/"):
                task_id = _task_id_from_path(parsed.path)
                task = self.context.monitor.delete_task(task_id)
                self._send_json({"task": task})
            elif parsed.path.startswith("/api/"):
                self._send_error(HTTPStatus.NOT_FOUND, "API not found")
            else:
                self._send_error(HTTPStatus.NOT_FOUND, "Not found")
        except Exception as exc:
            self._send_exception(exc)

    def _gpu_models_payload(self, config=None) -> dict[str, Any]:
        if config is None:
            config = load_config(ConfigPath)
        try:
            return platform_gpu_models(config)
        except Exception as exc:
            if isinstance(exc, PlatformNotSupported):
                raise
            self.context.state.add_event("warn", "GPU model lookup failed", {"error": str(exc), "provider": config.platform.provider})
            return platform_fallback_gpu_models(config, exc)

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"error": message}, status=status)

    def _send_exception(self, exc: Exception) -> None:
        if isinstance(exc, ConfigError):
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        elif isinstance(exc, PlatformNotSupported):
            self._send_error(HTTPStatus.NOT_IMPLEMENTED, str(exc))
        elif isinstance(exc, KeyError):
            self._send_error(HTTPStatus.NOT_FOUND, str(exc))
        elif isinstance(exc, ValueError):
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        else:
            self.context.state.add_event("error", "HTTP request failed", {"error": str(exc), "path": self.path})
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))


def _task_id_from_path(path: str, suffix: str = "") -> str:
    if suffix:
        path = path[: -len(suffix)]
    prefix = "/api/tasks/"
    if not path.startswith(prefix):
        raise ValueError("task path is invalid")
    task_id = path[len(prefix) :]
    if not task_id:
        raise ValueError("task_id is required")
    return task_id


def _task_name(body: dict[str, Any]) -> str:
    name = body.get("name")
    if not isinstance(name, str):
        raise ValueError("task name is required")
    return name


def _task_config(body: dict[str, Any]) -> dict[str, Any]:
    config = body.get("config")
    if not isinstance(config, dict):
        raise ValueError("task config is required")
    return config


def run_server(host: str, port: int) -> None:
    context = AppContext()

    class BoundHandler(RequestHandler):
        pass

    BoundHandler.context = context
    server = ThreadingHTTPServer((host, port), BoundHandler)
    print(f"VastAutoTools running at http://{host}:{port}")
    server.serve_forever()
