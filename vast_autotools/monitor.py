from __future__ import annotations

import threading
import time
import traceback
from dataclasses import asdict
from typing import Optional

from .config import AppConfig, ConfigPath, config_from_dict, config_to_dict, load_config, save_config
from .notifier import BarkMessage, build_notifier
from .platforms import PlatformAdapter, build_adapter, ensure_provider_supported
from .state import StateStore
from .tasks import TaskStore
from .vast_adapter import CreateResult, OfferView, extract_ssh_target


class MonitorService:
    def __init__(self, state: StateStore):
        self._state = state
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._task_store = TaskStore()

    def start(self) -> None:
        config = load_config(ConfigPath)
        self.start_task("default", config)

    def start_task(self, task_id: str, config: Optional[AppConfig] = None) -> None:
        if config is None:
            task = self._task_store.get_task(task_id)
            config = config_from_task(task)
            task_name = task.name
        else:
            task = self._task_store.upsert_task(task_id, _default_task_name(config), config)
            task_name = task.name
        ensure_provider_supported(config)
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                snapshot = self._state.snapshot()
                if snapshot.active_task_id != task_id:
                    raise RuntimeError(f"monitor task is already running: {snapshot.active_task_id}")
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, name=f"{config.platform.provider}-monitor", daemon=True)
            started_at = time.time()
            self._state.update(
                running=True,
                started_at=started_at,
                next_scan_at=started_at,
                active_task_id=task_id,
                active_task_name=task_name,
                active_task_config=config_to_dict(config),
            )
            self._task_store.update_runtime(
                task_id,
                status="running",
                last_started_at=started_at,
                last_error="",
                next_scan_at=started_at,
            )
            self._event(config, "info", "监控已启动", "Monitor started")
            self._thread.start()

    def stop(self) -> None:
        snapshot = self._state.snapshot()
        if snapshot.active_task_config is None:
            config = load_config(ConfigPath)
        else:
            config = config_from_task_config(snapshot.active_task_config)
        with self._lock:
            self._stop_event.set()
            self._state.update(
                running=False,
                next_scan_at=None,
                active_task_id=None,
                active_task_name="",
                active_task_config=None,
            )
            if snapshot.active_task_id is not None:
                self._task_store.update_runtime(
                    snapshot.active_task_id,
                    status="stopped",
                    last_stopped_at=time.time(),
                    next_scan_at=None,
                )
            self._event(config, "info", "监控已停止", "Monitor stopped")

    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()

    def _event(
        self,
        config: AppConfig,
        level: str,
        zh_message: str,
        en_message: str,
        data: Optional[dict] = None,
    ) -> None:
        message = en_message if config.ui.language == "en" else zh_message
        self._state.add_event(level, message, data)

    def scan_once(self) -> dict:
        config = load_config(ConfigPath)
        return self._scan_with_config(config)

    def list_tasks(self) -> list[dict]:
        tasks = self._task_store.list_tasks()
        snapshot = self._state.snapshot()
        return [_merge_runtime_task(task, snapshot) for task in tasks]

    def create_task(self, name: str, config: AppConfig) -> dict:
        return self._task_store.create_task(name, config).to_dict()

    def update_task(self, task_id: str, name: str, config: AppConfig) -> dict:
        task = self._task_store.update_task(task_id, name, config)
        snapshot = self._state.snapshot()
        if snapshot.active_task_id == task_id:
            self._state.update(active_task_name=task.name, active_task_config=task.config)
        return task.to_dict()

    def delete_task(self, task_id: str) -> dict:
        snapshot = self._state.snapshot()
        if snapshot.active_task_id == task_id and self.running():
            self.stop()
        return self._task_store.delete_task(task_id).to_dict()

    def update_config(self, config: AppConfig) -> None:
        save_config(config, ConfigPath)
        self._event(config, "info", "配置已保存", "Config saved")

    def update_target_offer_ids(self, offer_ids: list[int]) -> AppConfig:
        config = load_config(ConfigPath)
        config.create.target_offer_ids = offer_ids
        save_config(config, ConfigPath)
        self._event(
            config,
            "info",
            "自动创建目标已更新",
            "Auto-create target offer updated",
            {"target_offer_ids": offer_ids},
        )
        return config

    def send_test_bark(self) -> None:
        config = load_config(ConfigPath)
        notifier = build_notifier(
            config.credentials.bark_url,
            config.credentials.bark_group,
            config.credentials.bark_sound,
        )
        if notifier is None:
            raise ValueError("Bark URL is empty")
        notifier.send(
            BarkMessage(
                title=_text(config, "VastAutoTools 测试", "VastAutoTools test"),
                body=_text(config, "Bark 通知已配置", "Bark notification is configured"),
            )
        )
        self._event(config, "info", "Bark 测试通知已发送", "Bark test notification sent")

    def cleanup_failed_managed_instances(self) -> list[dict]:
        config = load_config(ConfigPath)
        adapter = build_adapter(config)
        cleaned = self._cleanup_failed_managed_instances(config, adapter)
        cleaned.extend(self._recheck_unverified_managed_instances(config, adapter, _handled_instance_ids(cleaned)))
        return cleaned

    def delete_instances(self, instance_ids: list[int | str]) -> list[dict]:
        config = load_config(ConfigPath)
        adapter = build_adapter(config)
        instances = {instance_id: instance for instance in adapter.list_instances() if (instance_id := _instance_id(instance)) is not None}
        deleted: list[dict] = []
        for instance_id in _unique_instance_ids(instance_ids):
            instance = instances.get(instance_id)
            if instance is None:
                item = _created_item_from_instance_id(instance_id)
            else:
                item = _created_item_from_instance(instance, config.connection.ssh_test_mode)
            item["cleanup"] = {"status": "deleting", "detail": "manual deletion requested"}
            self._state.update_created_instance(instance_id, item)
            self._event(
                config,
                "warn",
                f"已请求手动删除实例 {instance_id}",
                f"Manual deletion requested for instance {instance_id}",
                {"instance_id": instance_id},
            )
            try:
                destroy_response = adapter.destroy_instance(instance_id)
            except Exception as exc:
                item["cleanup"] = {"status": "delete_failed", "detail": str(exc)}
                self._state.update_created_instance(instance_id, item)
                self._event(
                    config,
                    "error",
                    f"实例 {instance_id} 手动删除失败",
                    f"Manual deletion failed for instance {instance_id}",
                    {"error": str(exc), "instance_id": instance_id},
                )
            else:
                item["cleanup"] = {
                    "status": "deleted",
                    "detail": "manual deletion completed",
                    "response": destroy_response,
                }
                self._state.update_created_instance(instance_id, item)
                self._event(
                    config,
                    "info",
                    f"实例 {instance_id} 手动删除完成",
                    f"Manual deletion completed for instance {instance_id}",
                    {"instance_id": instance_id, "response": destroy_response},
                )
            deleted.append(item)
        return deleted

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            snapshot = self._state.snapshot()
            if snapshot.active_task_config is None:
                config = load_config(ConfigPath)
                task_id = snapshot.active_task_id
            else:
                config = config_from_task_config(snapshot.active_task_config)
                task_id = snapshot.active_task_id
            started = time.time()
            self._state.update(next_scan_at=started + config.monitor.scan_interval_seconds)
            if task_id is not None:
                self._task_store.update_runtime(
                    task_id,
                    status="running",
                    next_scan_at=started + config.monitor.scan_interval_seconds,
                )
            try:
                result = self._scan_with_config(config)
                if task_id is not None:
                    after_scan = self._state.snapshot()
                    self._task_store.update_runtime(
                        task_id,
                        status="running",
                        last_scan_at=after_scan.last_scan_at,
                        next_scan_at=after_scan.next_scan_at,
                        cycles=after_scan.cycles,
                        last_error="",
                    )
                if result["capacity_reached"]:
                    self._event(
                        config,
                        "info",
                        "已达到托管实例数量上限，停止监控",
                        "Managed instance limit reached, stopping monitor",
                        {"max_created_instances": config.create.max_created_instances},
                    )
                    self.stop()
                    return
            except Exception as exc:
                self._handle_error(config, exc)
                if task_id is not None:
                    self._task_store.update_runtime(task_id, status="error", last_error=str(exc))
            self._stop_event.wait(config.monitor.scan_interval_seconds)
        self._state.update(
            running=False,
            next_scan_at=None,
            active_task_id=None,
            active_task_name="",
            active_task_config=None,
        )

    def _scan_with_config(self, config: AppConfig) -> dict:
        with self._lock:
            snapshot = self._state.snapshot()
            if snapshot.scan_in_progress:
                raise RuntimeError("A scan is already in progress")
            self._state.update(scan_in_progress=True, last_error="")

        try:
            started_at = time.time()
            adapter = build_adapter(config)
            offers = adapter.search()
            self._state.update(last_scan_at=started_at, cycles=self._state.snapshot().cycles + 1)
            self._state.set_recent_offers([offer.to_dict() for offer in offers[:50]])

            result: dict = {
                "matched": len(offers),
                "created": [],
                "auto_create_enabled": config.create.auto_create_enabled,
                "capacity_reached": False,
                "managed_instances": None,
            }
            if offers:
                self._event(
                    config,
                    "info",
                    f"扫描命中 {len(offers)} 个候选机器",
                    f"Scan matched {len(offers)} candidate offers",
                    {"top_offer": offers[0].to_dict()},
                )
            else:
                self._event(config, "info", "扫描完成，没有匹配报价", "Scan completed with no matching offers")

            if not config.create.auto_create_enabled:
                return result
            if not _has_ssh_private_key(config):
                result["ssh_key_missing"] = True
                self._event(
                    config,
                    "error",
                    "自动创建前必须填写 SSH 私钥路径或私钥内容用于验证登录",
                    "SSH private key path or private key is required before auto-create can verify login",
                )
                return result

            result["cleaned_instances"] = self._cleanup_failed_managed_instances(config, adapter)
            result["cleaned_instances"].extend(
                self._recheck_unverified_managed_instances(
                    config,
                    adapter,
                    _handled_instance_ids(result["cleaned_instances"]),
                )
            )
            deleted_ids = _deleted_instance_ids(result["cleaned_instances"])
            managed_before = _active_managed_instance_count(
                adapter.list_instances(),
                config.create.label_prefix.strip(),
                deleted_ids,
            )
            created_total_before = max(managed_before, _active_created_record_count(self._state.snapshot().created_instances))
            result["managed_instances"] = managed_before
            result["created_total"] = created_total_before
            remaining_capacity = config.create.max_created_instances - created_total_before
            if remaining_capacity <= 0:
                self._event(config, "info", "已达到托管实例数量上限，跳过创建", "Managed instance limit reached, skipping create")
                result["capacity_reached"] = True
                return result
            if not offers:
                return result

            create_limit = min(config.create.max_creates_per_cycle, remaining_capacity)
            target_offer_ids = set(config.create.target_offer_ids)
            create_candidates = offers
            if target_offer_ids:
                create_candidates = [offer for offer in offers if offer.id in target_offer_ids]
                if not create_candidates:
                    self._event(
                        config,
                        "warn",
                        "选中的自动创建 offer 已不在扫描结果中",
                        "Selected auto-create offer is no longer in scan results",
                    )
                    return result
            created_count = 0
            retained_created_count = 0
            for offer in create_candidates:
                if created_count >= create_limit:
                    break
                try:
                    created = adapter.create_instance(offer)
                except Exception as exc:
                    self._event(
                        config,
                        "warn",
                        f"offer {offer.id} 创建失败",
                        f"Create failed for offer {offer.id}",
                        {"error": str(exc), "offer": offer.to_dict()},
                    )
                    continue

                created_item = _created_item(created)
                created_item["connection_check"] = {
                    "ok": False,
                    "mode": config.connection.ssh_test_mode,
                    "detail": "created; waiting for connection check",
                }
                created_item["ssh"] = None
                self._state.add_created_instance(created_item)
                result["created"].append(created_item)
                created_count += 1
                self._event(
                    config,
                    "success",
                    f"实例 {created.instance_id} 已创建，正在检测 SSH",
                    f"Instance {created.instance_id} created; checking connection",
                    created_item,
                )

                try:
                    ready = adapter.wait_for_connection(created.instance_id)
                except Exception as exc:
                    created_item["connection_check"] = {
                        "ok": False,
                        "mode": config.connection.ssh_test_mode,
                        "detail": str(exc),
                    }
                    created_item["cleanup"] = {"status": "deleting", "detail": "connection check failed"}
                    self._state.update_created_instance(created.instance_id, created_item)
                    self._event(
                        config,
                        "warn",
                        f"实例 {created.instance_id} SSH 检测失败，正在删除实例",
                        f"Connection test failed for instance {created.instance_id}; deleting instance",
                        {"error": str(exc), "offer": offer.to_dict(), "instance_id": created.instance_id},
                    )
                    try:
                        destroy_response = adapter.destroy_instance(created.instance_id)
                    except Exception as destroy_exc:
                        created_item["cleanup"] = {"status": "delete_failed", "detail": str(destroy_exc)}
                        self._state.update_created_instance(created.instance_id, created_item)
                        retained_created_count += 1
                        self._event(
                            config,
                            "error",
                            f"实例 {created.instance_id} 连接失败后删除失败",
                            f"Failed to delete instance {created.instance_id} after connection failure",
                            {"error": str(destroy_exc), "instance_id": created.instance_id},
                        )
                    else:
                        created_item["cleanup"] = {
                            "status": "deleted",
                            "detail": "deleted after connection failure",
                            "response": destroy_response,
                        }
                        self._state.update_created_instance(created.instance_id, created_item)
                        self._event(
                            config,
                            "info",
                            f"实例 {created.instance_id} 连接失败后已删除",
                            f"Instance {created.instance_id} deleted after connection failure",
                            {"instance_id": created.instance_id, "response": destroy_response},
                        )
                    continue

                created_item["ssh"] = asdict(ready.target)
                created_item["connection_check"] = asdict(ready.check)
                created_item["cleanup"] = {"status": "kept", "detail": "connection test passed"}
                self._state.update_created_instance(created.instance_id, created_item)
                retained_created_count += 1
                self._event(
                    config,
                    "success",
                    f"实例 {created.instance_id} SSH 连接检测通过",
                    f"Instance {created.instance_id} connection test passed",
                    created_item,
                )
                self._notify_ready(config, created, ready.target.host, ready.target.port)

            if config.create.auto_create_enabled and not result["created"]:
                self._event(config, "warn", "已命中 offer，但没有实例创建成功", "Offers matched, but no instance was created")
            created_total_after = created_total_before + retained_created_count
            result["created_total"] = created_total_after
            result["capacity_reached"] = created_total_after >= config.create.max_created_instances
            return result
        finally:
            self._state.update(scan_in_progress=False)

    def _notify_ready(self, config: AppConfig, created: CreateResult, host: str, port: int) -> None:
        notifier = build_notifier(
            config.credentials.bark_url,
            config.credentials.bark_group,
            config.credentials.bark_sound,
        )
        if notifier is None:
            self._event(
                config,
                "warn",
                f"实例 {created.instance_id} 就绪通知已跳过：Bark URL 为空",
                f"Instance {created.instance_id} ready notification skipped; Bark URL is empty",
            )
            return
        offer = created.offer
        body = (
            f"{offer.num_gpus}x {offer.gpu_name}, ${offer.dph_total:.3f}/h, "
            f"{offer.flops_per_usd:.2f} TFLOPS/USD, ssh root@{host} -p {port}"
        )
        try:
            provider = _provider_label(config)
            notifier.send(
                BarkMessage(
                    title=_text(config, f"{provider} 实例 {created.instance_id} 已就绪", f"{provider} instance {created.instance_id} is ready"),
                    body=body,
                )
            )
            self._event(
                config,
                "success",
                f"实例 {created.instance_id} 就绪通知已发送",
                f"Instance {created.instance_id} ready notification sent",
            )
        except Exception as exc:
            self._event(config, "warn", "就绪通知发送失败", "Ready notification failed", {"error": str(exc), "instance_id": created.instance_id})

    def _cleanup_failed_managed_instances(self, config: AppConfig, adapter: PlatformAdapter) -> list[dict]:
        label_prefix = config.create.label_prefix.strip()
        cleaned: list[dict] = []
        for instance in adapter.list_instances():
            if not _is_managed_instance(instance, label_prefix):
                continue
            if not _instance_has_error(instance):
                continue
            instance_id = _instance_id(instance)
            if instance_id is None:
                continue

            item = _created_item_from_instance(instance, config.connection.ssh_test_mode)
            item["cleanup"] = {"status": "deleting", "detail": "existing managed instance is in error state"}
            self._state.update_created_instance(instance_id, item)
            self._event(
                config,
                "warn",
                f"托管实例 {instance_id} 处于 error 状态，正在删除",
                f"Managed instance {instance_id} is in error state; deleting instance",
                {"instance_id": instance_id, "status_msg": _instance_status_message(instance)},
            )
            try:
                destroy_response = adapter.destroy_instance(instance_id)
            except Exception as exc:
                item["cleanup"] = {"status": "delete_failed", "detail": str(exc)}
                self._state.update_created_instance(instance_id, item)
                self._event(
                    config,
                    "error",
                    f"托管 error 实例 {instance_id} 删除失败",
                    f"Failed to delete managed error instance {instance_id}",
                    {"error": str(exc), "instance_id": instance_id},
                )
            else:
                item["cleanup"] = {
                    "status": "deleted",
                    "detail": "deleted existing managed error instance",
                    "response": destroy_response,
                }
                self._state.update_created_instance(instance_id, item)
                self._event(
                    config,
                    "info",
                    f"托管 error 实例 {instance_id} 已删除",
                    f"Managed error instance {instance_id} deleted",
                    {"instance_id": instance_id, "response": destroy_response},
                )
            cleaned.append(item)
        return cleaned

    def _recheck_unverified_managed_instances(
        self,
        config: AppConfig,
        adapter: PlatformAdapter,
        skip_ids: set[int | str],
    ) -> list[dict]:
        snapshot = self._state.snapshot()
        handled: list[dict] = []
        records_by_id: dict[int | str, dict] = {}
        for item in snapshot.created_instances:
            instance_id = item.get("instance_id") if isinstance(item, dict) else None
            if _valid_instance_id(instance_id):
                records_by_id[instance_id] = item

        label_prefix = config.create.label_prefix.strip()
        for instance in adapter.list_instances():
            if not _is_managed_instance(instance, label_prefix):
                continue
            instance_id = _instance_id(instance)
            if instance_id is None or instance_id in skip_ids:
                continue
            item = records_by_id.get(instance_id)
            if _has_verified_ssh_record(item):
                continue
            if item is None:
                item = _created_item_from_instance(instance, config.connection.ssh_test_mode)

            item["cleanup"] = {"status": "checking", "detail": "verifying real SSH connection"}
            self._state.update_created_instance(instance_id, item)
            self._event(
                config,
                "info",
                f"正在验证托管实例 {instance_id} 的 SSH",
                f"Verifying SSH for managed instance {instance_id}",
                {"instance_id": instance_id, "timeout_seconds": config.connection.wait_timeout_seconds},
            )
            try:
                ready = adapter.wait_for_connection(instance_id)
            except Exception as exc:
                target = extract_ssh_target(instance, config.connection.ssh_user)
                if target is not None:
                    item["ssh"] = asdict(target)
                item["connection_check"] = {"ok": False, "mode": "ssh", "detail": str(exc)}
                item["cleanup"] = {"status": "deleting", "detail": "SSH did not pass within configured timeout"}
                self._state.update_created_instance(instance_id, item)
                self._event(
                    config,
                    "warn",
                    f"托管实例 {instance_id} SSH 验证失败，正在删除",
                    f"Managed instance {instance_id} failed SSH verification; deleting instance",
                    {"instance_id": instance_id, "check": item["connection_check"]},
                )
                try:
                    destroy_response = adapter.destroy_instance(instance_id)
                except Exception as destroy_exc:
                    item["cleanup"] = {"status": "delete_failed", "detail": str(destroy_exc)}
                    self._state.update_created_instance(instance_id, item)
                    self._event(
                        config,
                        "error",
                        f"SSH 失败的托管实例 {instance_id} 删除失败",
                        f"Failed to delete SSH-failed managed instance {instance_id}",
                        {"error": str(destroy_exc), "instance_id": instance_id},
                    )
                else:
                    item["cleanup"] = {
                        "status": "deleted",
                        "detail": "deleted because real SSH did not pass",
                        "response": destroy_response,
                    }
                    self._state.update_created_instance(instance_id, item)
                    self._event(
                        config,
                        "info",
                        f"托管实例 {instance_id} SSH 验证失败后已删除",
                        f"Managed instance {instance_id} deleted after SSH verification failed",
                        {"instance_id": instance_id, "response": destroy_response},
                    )
            else:
                item["ssh"] = asdict(ready.target)
                item["connection_check"] = asdict(ready.check)
                item["cleanup"] = {"status": "kept", "detail": "ssh command succeeded"}
                self._state.update_created_instance(instance_id, item)
                self._event(
                    config,
                    "success",
                    f"托管实例 {instance_id} SSH 验证通过",
                    f"Managed instance {instance_id} SSH verification passed",
                    item,
                )
            handled.append(item)
        return handled

    def _handle_error(self, config: AppConfig, exc: Exception) -> None:
        message = str(exc)
        self._state.update(last_error=message, scan_in_progress=False)
        self._event(config, "error", "监控扫描失败", "Monitor scan failed", {"error": message, "trace": traceback.format_exc()})
        if not config.monitor.notify_on_error:
            return
        notifier = build_notifier(
            config.credentials.bark_url,
            config.credentials.bark_group,
            config.credentials.bark_sound,
        )
        if notifier is None:
            return
        try:
            notifier.send(BarkMessage(title=_text(config, "VastAutoTools 扫描失败", "VastAutoTools scan failed"), body=message[:300]))
        except Exception as notify_exc:
            self._event(config, "warn", "错误通知发送失败", "Error notification failed", {"error": str(notify_exc)})


def _created_item(created: CreateResult) -> dict:
    return {
        "created_at": time.time(),
        "instance_id": created.instance_id,
        "label": created.label,
        "offer": created.offer.to_dict(),
        "response": created.response,
    }


def config_from_task(task) -> AppConfig:
    return config_from_task_config(task.config)


def config_from_task_config(raw_config: dict) -> AppConfig:
    return config_from_dict(raw_config)


def _default_task_name(config: AppConfig) -> str:
    provider = _provider_label(config)
    gpu_names = ", ".join(config.search.gpu_names)
    if gpu_names:
        return f"{provider} {gpu_names}"
    return f"{provider} monitor"


def _merge_runtime_task(task: dict, snapshot) -> dict:
    if snapshot.active_task_id != task["id"]:
        task["active"] = False
        return task
    task["active"] = True
    task["status"] = "running" if snapshot.running else task["status"]
    task["last_scan_at"] = snapshot.last_scan_at
    task["next_scan_at"] = snapshot.next_scan_at
    task["cycles"] = snapshot.cycles
    task["last_error"] = snapshot.last_error
    return task


def _text(config: AppConfig, zh_message: str, en_message: str) -> str:
    return en_message if config.ui.language == "en" else zh_message


def _has_ssh_private_key(config: AppConfig) -> bool:
    return bool(config.connection.ssh_private_key_path.strip() or config.connection.ssh_private_key.strip())


def _provider_label(config: AppConfig) -> str:
    if config.platform.provider == "vast":
        return "Vast"
    if config.platform.provider == "runpod":
        return "RunPod"
    return config.platform.provider


def _created_item_from_instance(instance: dict, ssh_test_mode: str) -> dict:
    instance_id = _instance_id(instance)
    return {
        "created_at": _instance_start_time(instance),
        "instance_id": instance_id,
        "label": str(instance.get("label") or ""),
        "offer": {
            "gpu_name": instance.get("gpu_name"),
            "num_gpus": instance.get("num_gpus"),
            "dph_total": instance.get("dph_total"),
            "flops_per_usd": instance.get("flops_per_dphtotal"),
            "geolocation": instance.get("geolocation"),
        },
        "response": {},
        "ssh": _ssh_from_instance(instance),
        "connection_check": {
            "ok": False,
            "mode": ssh_test_mode,
            "detail": _instance_status_message(instance),
        },
    }


def _created_item_from_instance_id(instance_id: int | str) -> dict:
    return {
        "created_at": time.time(),
        "instance_id": instance_id,
        "label": "",
        "offer": {},
        "response": {},
        "ssh": None,
        "connection_check": {
            "ok": False,
            "mode": "ssh",
            "detail": "instance was not returned by Vast before deletion",
        },
    }


def _is_managed_instance(instance: dict, label_prefix: str) -> bool:
    if not label_prefix:
        return False
    label = instance.get("label")
    return isinstance(label, str) and label.startswith(label_prefix)


def _instance_has_error(instance: dict) -> bool:
    status_values = [
        instance.get("actual_status"),
        instance.get("cur_state"),
        instance.get("next_state"),
        instance.get("intended_status"),
        instance.get("status"),
    ]
    if any(isinstance(value, str) and value.lower() in {"error", "failed"} for value in status_values):
        return True
    if _instance_has_conflicting_loading_state(instance):
        return True
    status_msg = instance.get("status_msg")
    return isinstance(status_msg, str) and "error" in status_msg.lower()


def _instance_has_conflicting_loading_state(instance: dict) -> bool:
    actual_status = instance.get("actual_status")
    if not isinstance(actual_status, str) or actual_status.lower() != "loading":
        return False
    stopped_values = [instance.get("cur_state"), instance.get("next_state"), instance.get("intended_status")]
    return any(isinstance(value, str) and value.lower() == "stopped" for value in stopped_values)


def _instance_id(instance: dict) -> Optional[int | str]:
    instance_id = instance.get("id") or instance.get("instance_id")
    if isinstance(instance_id, int) and not isinstance(instance_id, bool):
        return instance_id
    if isinstance(instance_id, str) and instance_id.strip():
        if instance_id.isdigit():
            return int(instance_id)
        return instance_id.strip()
    return None


def _instance_start_time(instance: dict) -> float:
    value = instance.get("start_date")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return time.time()


def _ssh_from_instance(instance: dict) -> Optional[dict]:
    host = instance.get("ssh_host") or instance.get("public_ipaddr")
    port = instance.get("ssh_port")
    if isinstance(host, str) and host.strip() and isinstance(port, int) and port > 0:
        return {"host": host.strip(), "port": port, "user": "root"}
    return None


def _instance_status_message(instance: dict) -> str:
    status_msg = instance.get("status_msg")
    if isinstance(status_msg, str) and status_msg.strip():
        return status_msg.strip()
    statuses = [
        str(instance.get("actual_status") or ""),
        str(instance.get("cur_state") or ""),
    ]
    return " / ".join(status for status in statuses if status)


def _active_created_record_count(items: list[dict]) -> int:
    active_ids: set[int | str] = set()
    for item in items:
        instance_id = item.get("instance_id")
        if not _valid_instance_id(instance_id):
            continue
        cleanup = item.get("cleanup")
        cleanup_status = cleanup.get("status") if isinstance(cleanup, dict) else ""
        if cleanup_status == "deleted":
            continue
        active_ids.add(instance_id)
    return len(active_ids)


def _handled_instance_ids(items: list[dict]) -> set[int | str]:
    ids: set[int | str] = set()
    for item in items:
        instance_id = item.get("instance_id") if isinstance(item, dict) else None
        if _valid_instance_id(instance_id):
            ids.add(instance_id)
    return ids


def _deleted_instance_ids(items: list[dict]) -> set[int | str]:
    ids: set[int | str] = set()
    for item in items:
        instance_id = item.get("instance_id") if isinstance(item, dict) else None
        cleanup = item.get("cleanup") if isinstance(item, dict) else None
        status = cleanup.get("status") if isinstance(cleanup, dict) else ""
        if _valid_instance_id(instance_id) and status == "deleted":
            ids.add(instance_id)
    return ids


def _active_managed_instance_count(instances: list[dict], label_prefix: str, deleted_ids: set[int | str]) -> int:
    count = 0
    for instance in instances:
        instance_id = _instance_id(instance)
        if instance_id is not None and instance_id in deleted_ids:
            continue
        if _is_managed_instance(instance, label_prefix):
            count += 1
    return count


def _has_verified_ssh_record(item: Optional[dict]) -> bool:
    if item is None:
        return False
    check = item.get("connection_check")
    cleanup = item.get("cleanup")
    if not isinstance(check, dict) or check.get("mode") != "ssh" or check.get("ok") is not True:
        return False
    if isinstance(cleanup, dict) and cleanup.get("status") == "deleted":
        return False
    return True


def _unique_instance_ids(instance_ids: list[int | str]) -> list[int | str]:
    seen: set[int | str] = set()
    result: list[int | str] = []
    for instance_id in instance_ids:
        if not _valid_instance_id(instance_id):
            raise ValueError("instance_ids must contain non-empty strings or integers")
        if instance_id in seen:
            continue
        seen.add(instance_id)
        result.append(instance_id)
    return result


def _valid_instance_id(instance_id) -> bool:
    if isinstance(instance_id, int) and not isinstance(instance_id, bool):
        return True
    return isinstance(instance_id, str) and bool(instance_id.strip())
