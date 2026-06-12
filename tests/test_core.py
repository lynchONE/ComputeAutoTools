import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from vast_autotools.config import ConfigError, config_from_dict, config_to_dict, default_config
from vast_autotools.monitor import MonitorService, _active_created_record_count, _unique_instance_ids
from vast_autotools.monitor import _instance_has_error, _is_managed_instance
from vast_autotools.platforms import PlatformNotSupported, build_adapter, platform_gpu_models
from vast_autotools.runpod_adapter import RunPodAdapter, _normalize_pod
from vast_autotools.state import StateStore
from vast_autotools.stock_alerts import StockAlertStore
from vast_autotools.tasks import TaskStore
from vast_autotools.vast_adapter import (
    CreateResult,
    InstanceReadyResult,
    OfferView,
    VastAdapter,
    build_order,
    build_search_query,
    extract_ssh_target,
    sort_offers,
)
from vast_autotools.ssh_check import ConnectionCheckResult, SshTarget, check_connection
from vast_autotools.server import RequestHandler


class ConfigTests(unittest.TestCase):
    def test_round_trip_default_config(self):
        config = default_config()
        parsed = config_from_dict(config_to_dict(config))
        self.assertEqual(parsed.search.min_gpu_count, 1)
        self.assertFalse(parsed.create.auto_create_enabled)
        self.assertEqual(parsed.connection.ssh_test_mode, "ssh")
        self.assertEqual(parsed.ui.language, "zh")
        self.assertEqual(parsed.platform.provider, "vast")

    def test_migrates_legacy_tcp_connection_mode_to_ssh(self):
        raw = config_to_dict(default_config())
        raw["connection"]["ssh_test_mode"] = "tcp"
        parsed = config_from_dict(raw)
        self.assertEqual(parsed.connection.ssh_test_mode, "ssh")

    def test_keeps_user_configured_wait_timeout(self):
        raw = config_to_dict(default_config())
        raw["connection"]["wait_timeout_seconds"] = 900
        parsed = config_from_dict(raw)
        self.assertEqual(parsed.connection.wait_timeout_seconds, 900)

    def test_rejects_unknown_fields(self):
        raw = config_to_dict(default_config())
        raw["search"]["unknown"] = True
        with self.assertRaises(ConfigError):
            config_from_dict(raw)

    def test_auto_create_requires_api_key(self):
        raw = config_to_dict(default_config())
        raw["create"]["auto_create_enabled"] = True
        with self.assertRaises(ConfigError):
            config_from_dict(raw)

    def test_normalizes_combined_gpu_name_from_old_text_input(self):
        raw = config_to_dict(default_config())
        raw["search"]["gpu_names"] = ["RTX 4090 RTX 5090"]
        parsed = config_from_dict(raw)
        self.assertEqual(parsed.search.gpu_names, ["RTX 4090", "RTX 5090"])

    def test_target_offer_ids_round_trip(self):
        raw = config_to_dict(default_config())
        raw["create"]["target_offer_ids"] = [123, 456]
        parsed = config_from_dict(raw)
        self.assertEqual(parsed.create.target_offer_ids, [123, 456])

    def test_allow_create_without_ssh_key_round_trip(self):
        raw = config_to_dict(default_config())
        raw["create"]["allow_create_without_ssh_key"] = True
        parsed = config_from_dict(raw)
        self.assertTrue(parsed.create.allow_create_without_ssh_key)

    def test_stock_alert_config_round_trip(self):
        raw = config_to_dict(default_config())
        raw["monitor"]["stock_alert_enabled"] = True
        raw["monitor"]["stock_alert_window_minutes"] = 30
        raw["monitor"]["stock_alert_min_baseline_count"] = 8
        raw["monitor"]["stock_alert_drop_count"] = 4
        raw["monitor"]["stock_alert_drop_percent"] = 25.5
        raw["monitor"]["stock_alert_cooldown_minutes"] = 45
        parsed = config_from_dict(raw)
        self.assertTrue(parsed.monitor.stock_alert_enabled)
        self.assertEqual(parsed.monitor.stock_alert_window_minutes, 30)
        self.assertEqual(parsed.monitor.stock_alert_min_baseline_count, 8)
        self.assertEqual(parsed.monitor.stock_alert_drop_count, 4)
        self.assertEqual(parsed.monitor.stock_alert_drop_percent, 25.5)
        self.assertEqual(parsed.monitor.stock_alert_cooldown_minutes, 45)

    def test_builds_runpod_adapter(self):
        raw = config_to_dict(default_config())
        raw["platform"]["provider"] = "runpod"
        raw["credentials"]["runpod_api_key"] = "runpod-key"
        parsed = config_from_dict(raw)
        self.assertEqual(parsed.platform.provider, "runpod")
        self.assertIsInstance(build_adapter(parsed), RunPodAdapter)

    def test_rejects_invalid_target_offer_id(self):
        raw = config_to_dict(default_config())
        raw["create"]["target_offer_ids"] = [0]
        with self.assertRaises(ConfigError):
            config_from_dict(raw)


class QueryTests(unittest.TestCase):
    def test_query_builds_gpu_price_and_geo_filters(self):
        config = default_config()
        config.search.gpu_names = ["RTX 4090", "RTX 3090"]
        config.search.min_gpu_count = 2
        config.search.max_price_per_hour = 0.75
        config.search.geolocations_block = ["CN", "VN"]
        query = build_search_query(config.search)
        self.assertIn('gpu_name in ["RTX 4090","RTX 3090"]', query)
        self.assertIn("num_gpus>=2", query)
        self.assertIn("dph<=0.75", query)
        self.assertIn("geolocation notin [CN,VN]", query)

    def test_order_uses_vast_alias(self):
        self.assertEqual(build_order("flops_per_usd"), "flops_usd-")
        self.assertEqual(build_order("price"), "dph")


class OfferTests(unittest.TestCase):
    def test_sort_flops_per_usd(self):
        offers = [
            OfferView(1, "A", 1, 2.0, 20.0, 10.0, None, None, "US", None, None, None, {}),
            OfferView(2, "B", 1, 1.0, 30.0, 30.0, None, None, "US", None, None, None, {}),
        ]
        sorted_offers = sort_offers(offers, "flops_per_usd")
        self.assertEqual(sorted_offers[0].id, 2)

    def test_extract_ssh_target_from_ports_json(self):
        target = extract_ssh_target(
            {"public_ipaddr": "203.0.113.8", "ports": '{"22/tcp":[{"HostPort":"32123"}]}'},
            "root",
        )
        self.assertIsNotNone(target)
        self.assertEqual(target.host, "203.0.113.8")
        self.assertEqual(target.port, 32123)


class GpuModelTests(unittest.TestCase):
    def test_fallback_gpu_models_are_available(self):
        from vast_autotools.vast_adapter import FallbackGpuModels

        self.assertIn("RTX 4090", FallbackGpuModels)
        self.assertIn("H100 SXM", FallbackGpuModels)


class TaskStoreTests(unittest.TestCase):
    def test_task_store_crud_round_trip(self):
        config = default_config()
        config.credentials.vast_api_key = "test-key"
        config.search.gpu_names = ["H100 SXM"]

        with TemporaryDirectory() as tempdir:
            store = TaskStore(Path(tempdir) / "tasks.json")
            created = store.create_task("H100 task", config, task_id="task_a")
            self.assertEqual(created.id, "task_a")
            self.assertEqual(store.list_tasks()[0]["config"]["search"]["gpu_names"], ["H100 SXM"])

            config.search.gpu_names = ["RTX 4090"]
            updated = store.update_task("task_a", "RTX task", config)
            self.assertEqual(updated.name, "RTX task")
            self.assertEqual(store.get_task("task_a").config["search"]["gpu_names"], ["RTX 4090"])

            runtime = store.update_runtime("task_a", status="running", cycles=2)
            self.assertEqual(runtime.status, "running")
            self.assertEqual(runtime.cycles, 2)

            deleted = store.delete_task("task_a")
            self.assertEqual(deleted.id, "task_a")
            self.assertEqual(store.list_tasks(), [])


class StateStoreTests(unittest.TestCase):
    def test_clear_events_removes_memory_and_persisted_logs(self):
        with TemporaryDirectory() as tempdir:
            events_path = Path(tempdir) / "events.json"
            state = StateStore(events_path)
            state.add_event("info", "one")
            state.add_event("warn", "two")
            self.assertEqual(len(state.snapshot().events), 2)

            state.clear_events()

            self.assertEqual(state.snapshot().events, [])
            reloaded = StateStore(events_path)
            self.assertEqual(reloaded.snapshot().events, [])


class MonitorTests(unittest.TestCase):
    def test_deleted_failed_connection_records_do_not_count_against_limit(self):
        items = [
            {"instance_id": 1, "cleanup": {"status": "deleted"}},
            {"instance_id": 2, "cleanup": {"status": "kept"}},
            {"instance_id": 3, "cleanup": {"status": "delete_failed"}},
            {"instance_id": 3, "cleanup": {"status": "delete_failed"}},
        ]

        self.assertEqual(_active_created_record_count(items), 2)

    def test_managed_error_instance_detection(self):
        instance = {
            "id": 123,
            "label": "vast-auto-123",
            "actual_status": "loading",
            "cur_state": "stopped",
            "status_msg": "Error response from daemon",
        }

        self.assertTrue(_is_managed_instance(instance, "vast-auto"))
        self.assertTrue(_instance_has_error(instance))

    def test_loading_stopped_instance_is_treated_as_error(self):
        instance = {
            "id": 123,
            "label": "vast-auto-123",
            "actual_status": "loading",
            "cur_state": "stopped",
            "next_state": "stopped",
            "intended_status": "stopped",
            "status_msg": None,
        }

        self.assertTrue(_instance_has_error(instance))

    def test_auto_create_continues_until_total_limit_is_reached(self):
        sequence = []
        offers = [_offer(1), _offer(2)]

        class FakeAdapter:
            def __init__(self, config):
                self.config = config

            def search(self):
                return offers

            def count_managed_instances(self):
                return 0

            def list_instances(self):
                return []

            def create_instance(self, offer):
                if offer.id == 2:
                    raise RuntimeError("sold out")
                instance_id = 1000 + offer.id
                sequence.append(("create", instance_id))
                return CreateResult(offer=offer, response={"success": True}, instance_id=instance_id, label="test")

            def wait_for_connection(self, instance_id):
                sequence.append(("wait", instance_id))
                raise TimeoutError("not ready")

            def destroy_instance(self, instance_id):
                sequence.append(("destroy", instance_id))
                return {"success": True}

        notifier = _FakeNotifier(sequence)
        config = _auto_create_config(max_created_instances=2, max_creates_per_cycle=2)
        result = _scan_with_fakes(config, FakeAdapter, notifier, with_private_key=True)

        self.assertEqual(len(result["created"]), 1)
        self.assertFalse(result["capacity_reached"])
        self.assertEqual(sequence, [("create", 1001), ("wait", 1001), ("destroy", 1001)])
        self.assertEqual(result["created"][0]["cleanup"]["status"], "deleted")

    def test_auto_create_skips_without_ssh_private_key(self):
        sequence = []
        offers = [_offer(1)]

        class FakeAdapter:
            def __init__(self, config):
                self.config = config

            def search(self):
                return offers

            def create_instance(self, offer):
                sequence.append(("create", offer.id))
                raise AssertionError("create should not run without an SSH private key")

        config = _auto_create_config(max_created_instances=1, max_creates_per_cycle=1)
        result = _scan_with_fakes(config, FakeAdapter, _FakeNotifier(sequence))

        self.assertTrue(result["ssh_key_missing"])
        self.assertEqual(sequence, [])

    def test_auto_create_without_ssh_key_when_risk_is_accepted(self):
        sequence = []
        offers = [_offer(1)]

        class FakeAdapter:
            def __init__(self, config):
                self.config = config

            def search(self):
                return offers

            def list_instances(self):
                return []

            def create_instance(self, offer):
                instance_id = 1000 + offer.id
                sequence.append(("create", instance_id))
                return CreateResult(offer=offer, response={"success": True}, instance_id=instance_id, label="test")

            def wait_for_connection(self, instance_id):
                sequence.append(("wait", instance_id))
                raise AssertionError("SSH verification should be skipped")

            def destroy_instance(self, instance_id):
                sequence.append(("destroy", instance_id))
                raise AssertionError("unverified instance should be retained")

        config = _auto_create_config(max_created_instances=1, max_creates_per_cycle=1)
        config.create.allow_create_without_ssh_key = True
        result = _scan_with_fakes(config, FakeAdapter, _FakeNotifier(sequence))

        self.assertTrue(result["ssh_verification_skipped"])
        self.assertNotIn("ssh_key_missing", result)
        self.assertEqual(sequence, [("create", 1001)])
        self.assertEqual(result["created_total"], 1)
        self.assertTrue(result["capacity_reached"])
        created = result["created"][0]
        self.assertEqual(created["connection_check"]["mode"], "none")
        self.assertEqual(created["cleanup"]["status"], "kept_unverified")
        self.assertIn("billing risk accepted", created["cleanup"]["detail"])

    def test_stock_drop_alert_sends_notification_once_per_cooldown(self):
        sequence = []

        class FakeAdapter:
            counts = [10, 4, 3]

            def __init__(self, config):
                self.config = config

            def search(self):
                count = self.counts.pop(0)
                return [_offer(offer_id) for offer_id in range(1, count + 1)]

        notifier = _FakeNotifier(sequence)
        config = default_config()
        config.credentials.vast_api_key = "test-key"
        config.search.gpu_names = ["RTX 4090"]
        config.monitor.stock_alert_enabled = True
        config.monitor.stock_alert_window_minutes = 60
        config.monitor.stock_alert_min_baseline_count = 5
        config.monitor.stock_alert_drop_count = 5
        config.monitor.stock_alert_drop_percent = 30.0
        config.monitor.stock_alert_cooldown_minutes = 60

        with TemporaryDirectory() as tempdir:
            state = StateStore(Path(tempdir) / "events.json")
            service = MonitorService(state)
            service._stock_alert_store = StockAlertStore(Path(tempdir) / "stock_alerts.json")
            with (
                patch("vast_autotools.monitor.build_adapter", side_effect=lambda current_config: FakeAdapter(current_config)),
                patch("vast_autotools.monitor.build_notifier", return_value=notifier),
            ):
                first = service._scan_with_config(config, task_id="task-a")
                second = service._scan_with_config(config, task_id="task-a")
                third = service._scan_with_config(config, task_id="task-a")

        self.assertEqual(first["stock_alert"]["reason"], "warming_up")
        self.assertTrue(second["stock_alert"]["should_alert"])
        self.assertEqual(second["stock_alert"]["baseline_count"], 10)
        self.assertEqual(second["stock_alert"]["drop_count"], 6)
        self.assertFalse(third["stock_alert"]["should_alert"])
        self.assertEqual(third["stock_alert"]["reason"], "cooldown")
        self.assertEqual(sequence, [("notify", "GPU 库存下降告警")])

    def test_stock_alert_disabled_does_not_add_scan_result(self):
        class FakeAdapter:
            def __init__(self, config):
                self.config = config

            def search(self):
                return [_offer(1)]

        config = default_config()
        config.credentials.vast_api_key = "test-key"
        with TemporaryDirectory() as tempdir:
            state = StateStore(Path(tempdir) / "events.json")
            service = MonitorService(state)
            service._stock_alert_store = StockAlertStore(Path(tempdir) / "stock_alerts.json")
            with patch("vast_autotools.monitor.build_adapter", side_effect=lambda current_config: FakeAdapter(current_config)):
                result = service._scan_with_config(config, task_id="task-a")

        self.assertNotIn("stock_alert", result)

    def test_auto_create_accepts_inline_ssh_private_key(self):
        sequence = []
        offers = [_offer(1)]

        class FakeAdapter:
            def __init__(self, config):
                self.config = config

            def search(self):
                return offers

            def list_instances(self):
                return []

            def create_instance(self, offer):
                sequence.append(("create", offer.id))
                raise RuntimeError("stop after key gate")

        config = _auto_create_config(max_created_instances=1, max_creates_per_cycle=1)
        config.connection.ssh_private_key = "-----BEGIN OPENSSH PRIVATE KEY-----\ntest\n-----END OPENSSH PRIVATE KEY-----"
        result = _scan_with_fakes(config, FakeAdapter, _FakeNotifier(sequence))

        self.assertNotIn("ssh_key_missing", result)
        self.assertEqual(sequence, [("create", 1)])

    def test_auto_create_stops_at_total_limit_and_notifies_each_created_instance(self):
        sequence = []
        offers = [_offer(1), _offer(2), _offer(3)]

        class FakeAdapter:
            def __init__(self, config):
                self.config = config

            def search(self):
                return offers

            def count_managed_instances(self):
                return 0

            def list_instances(self):
                return []

            def create_instance(self, offer):
                instance_id = 1000 + offer.id
                sequence.append(("create", instance_id))
                return CreateResult(offer=offer, response={"success": True}, instance_id=instance_id, label="test")

            def wait_for_connection(self, instance_id):
                sequence.append(("wait", instance_id))
                return InstanceReadyResult(
                    instance={},
                    target=SshTarget(host="203.0.113.8", port=32123, user="root"),
                    check=ConnectionCheckResult(ok=True, mode="ssh", detail="ok"),
                )

            def destroy_instance(self, instance_id):
                sequence.append(("destroy", instance_id))
                return {"success": True}

        notifier = _FakeNotifier(sequence)
        config = _auto_create_config(max_created_instances=2, max_creates_per_cycle=5)
        result = _scan_with_fakes(config, FakeAdapter, notifier, with_private_key=True)

        self.assertEqual([item["instance_id"] for item in result["created"]], [1001, 1002])
        self.assertTrue(result["capacity_reached"])
        self.assertNotIn(("create", 1003), sequence)
        self.assertEqual(
            [item for item in sequence if item[0] == "notify"],
            [("notify", "Vast 实例 1001 已就绪"), ("notify", "Vast 实例 1002 已就绪")],
        )

    def test_cleanup_errors_skips_ssh_recheck_without_private_key(self):
        sequence = []
        config = default_config()
        config.credentials.vast_api_key = "test-key"
        config.create.label_prefix = "vast-auto"

        class FakeAdapter:
            def __init__(self, config):
                self.config = config

            def list_instances(self):
                return [{"id": 1001, "label": "vast-auto-1001", "actual_status": "running"}]

            def wait_for_connection(self, instance_id):
                sequence.append(("wait", instance_id))
                raise AssertionError("SSH recheck should be skipped without a private key")

            def destroy_instance(self, instance_id):
                sequence.append(("destroy", instance_id))
                raise AssertionError("running unverified instance should be retained")

        with TemporaryDirectory() as tempdir:
            state = StateStore(Path(tempdir) / "events.json")
            service = MonitorService(state)
            with (
                patch("vast_autotools.monitor.load_config", return_value=config),
                patch("vast_autotools.monitor.build_adapter", side_effect=lambda current_config: FakeAdapter(current_config)),
            ):
                cleaned = service.cleanup_failed_managed_instances()

        self.assertEqual(cleaned, [])
        self.assertEqual(sequence, [])

    def test_manual_delete_instances_records_attempt_and_result(self):
        sequence = []
        config = default_config()
        config.credentials.vast_api_key = "test-key"

        class FakeAdapter:
            def __init__(self, config):
                self.config = config

            def list_instances(self):
                return [{"id": 101, "label": "manual", "actual_status": "running"}]

            def destroy_instance(self, instance_id):
                sequence.append(("destroy", instance_id))
                return {"success": True, "id": instance_id}

        with TemporaryDirectory() as tempdir:
            state = StateStore(Path(tempdir) / "events.json")
            service = MonitorService(state)
            with (
                patch("vast_autotools.monitor.load_config", return_value=config),
                patch("vast_autotools.monitor.build_adapter", side_effect=lambda current_config: FakeAdapter(current_config)),
            ):
                deleted = service.delete_instances([101, 101])

        self.assertEqual(sequence, [("destroy", 101)])
        self.assertEqual(deleted[0]["cleanup"]["status"], "deleted")

    def test_manual_delete_accepts_string_instance_ids(self):
        sequence = []
        config = default_config()
        config.platform.provider = "runpod"
        config.credentials.runpod_api_key = "runpod-key"

        class FakeAdapter:
            def __init__(self, config):
                self.config = config

            def list_instances(self):
                return [{"id": "podabc123", "label": "manual", "actual_status": "running"}]

            def destroy_instance(self, instance_id):
                sequence.append(("destroy", instance_id))
                return {"success": True, "id": instance_id}

        with TemporaryDirectory() as tempdir:
            state = StateStore(Path(tempdir) / "events.json")
            service = MonitorService(state)
            with (
                patch("vast_autotools.monitor.load_config", return_value=config),
                patch("vast_autotools.monitor.build_adapter", side_effect=lambda current_config: FakeAdapter(current_config)),
            ):
                deleted = service.delete_instances(["podabc123", "podabc123"])

        self.assertEqual(sequence, [("destroy", "podabc123")])
        self.assertEqual(deleted[0]["instance_id"], "podabc123")
        self.assertEqual(deleted[0]["cleanup"]["status"], "deleted")

    def test_unique_instance_ids_rejects_invalid_values(self):
        with self.assertRaises(ValueError):
            _unique_instance_ids([1, True])


class VastAdapterTests(unittest.TestCase):
    def test_list_instances_filters_non_object_rows(self):
        config = default_config()
        config.credentials.vast_api_key = "test-key"
        adapter = VastAdapter.__new__(VastAdapter)
        adapter.config = config
        adapter._sdk = _FakeSdk([{"id": 1}, "bad", {"id": 2}])

        self.assertEqual(adapter.list_instances(), [{"id": 1}, {"id": 2}])

    def test_destroy_instance_returns_sdk_response(self):
        config = default_config()
        config.credentials.vast_api_key = "test-key"
        adapter = VastAdapter.__new__(VastAdapter)
        adapter.config = config
        adapter._sdk = _FakeSdk([])

        self.assertEqual(adapter.destroy_instance(123), {"success": True, "id": 123})

    def test_search_templates_filters_and_sorts(self):
        config = default_config()
        config.credentials.vast_api_key = "test-key"
        adapter = VastAdapter.__new__(VastAdapter)
        adapter.config = config
        adapter._sdk = _FakeSdk(
            [],
            templates=[
                {"name": "Other", "hash_id": "b", "recommended": False, "count_created": 50, "image": "ubuntu"},
                {"name": "PyTorch", "hash_id": "a", "recommended": True, "count_created": 10, "image": "pytorch/pytorch"},
            ],
        )

        self.assertEqual(adapter.search_templates(keyword="torch")[0]["hash_id"], "a")


class RunPodAdapterTests(unittest.TestCase):
    def test_search_maps_gpu_types_to_offers(self):
        config = default_config()
        config.platform.provider = "runpod"
        config.credentials.runpod_api_key = "runpod-key"
        config.search.gpu_names = ["RTX 4090"]
        config.search.min_gpu_count = 2
        config.search.max_price_per_hour = 1.0
        adapter = RunPodAdapter.__new__(RunPodAdapter)
        adapter.config = config
        adapter._client = _FakeRunPodClient(
            gpu_types=[
                {
                    "id": "NVIDIA GeForce RTX 4090",
                    "displayName": "RTX 4090",
                    "memoryInGb": 24,
                    "secure2": {
                        "stockStatus": "High",
                        "uninterruptablePrice": 0.45,
                        "availableGpuCounts": None,
                    },
                },
                {
                    "id": "NVIDIA RTX A4000",
                    "displayName": "RTX A4000",
                    "memoryInGb": 16,
                    "secure2": {
                        "stockStatus": "None",
                        "uninterruptablePrice": 0.2,
                        "availableGpuCounts": None,
                    },
                },
            ]
        )

        offers = adapter.search()

        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].gpu_name, "RTX 4090")
        self.assertEqual(offers[0].num_gpus, 2)
        self.assertEqual(offers[0].dph_total, 0.9)
        self.assertEqual(offers[0].raw["gpu_type_id"], "NVIDIA GeForce RTX 4090")

    def test_create_instance_uses_runpod_pod_id(self):
        config = default_config()
        config.platform.provider = "runpod"
        config.credentials.runpod_api_key = "runpod-key"
        config.create.image = "runpod/pytorch"
        adapter = RunPodAdapter.__new__(RunPodAdapter)
        adapter.config = config
        adapter._client = _FakeRunPodClient(created_pod={"id": "podabc123", "name": "created", "publicIp": "203.0.113.8"})
        offer = OfferView(
            123,
            "RTX 4090",
            1,
            0.5,
            82.6,
            165.2,
            1.0,
            24.0,
            "RunPod",
            None,
            None,
            1.0,
            {"gpu_type_id": "NVIDIA GeForce RTX 4090", "cloud_type": "SECURE", "price_per_gpu": 0.5, "stock_status": "High"},
        )

        created = adapter.create_instance(offer)

        self.assertEqual(created.instance_id, "podabc123")
        self.assertEqual(adapter._client.last_create["gpuTypeIds"], ["NVIDIA GeForce RTX 4090"])
        self.assertEqual(adapter._client.last_create["imageName"], "runpod/pytorch")
        self.assertEqual(adapter._client.last_create["ports"], ["22/tcp"])
        self.assertNotIn("interruptible", adapter._client.last_create)

    def test_normalize_pod_exposes_common_instance_fields(self):
        normalized = _normalize_pod(
            {
                "id": "podabc123",
                "name": "vast-auto-1",
                "publicIp": "203.0.113.8",
                "portMappings": {"22": 32123},
                "desiredStatus": "RUNNING",
                "costPerHr": 0.5,
                "gpu": {"displayName": "RTX 4090", "count": 1},
                "machine": {"location": "US"},
            }
        )

        self.assertEqual(normalized["instance_id"], "podabc123")
        self.assertEqual(normalized["label"], "vast-auto-1")
        self.assertEqual(normalized["ssh_host"], "203.0.113.8")
        self.assertEqual(normalized["ssh_port"], 32123)
        self.assertEqual(normalized["gpu_name"], "RTX 4090")

    def test_search_uses_min_gpu_count_when_runpod_omits_available_counts(self):
        config = default_config()
        config.platform.provider = "runpod"
        config.credentials.runpod_api_key = "runpod-key"
        config.search.gpu_names = ["RTX 5090"]
        config.search.min_gpu_count = 1
        config.search.max_price_per_hour = 2.0
        adapter = RunPodAdapter.__new__(RunPodAdapter)
        adapter.config = config
        adapter._client = _FakeRunPodClient(
            gpu_types=[
                {
                    "id": "NVIDIA GeForce RTX 5090",
                    "displayName": "RTX 5090",
                    "memoryInGb": 32,
                    "secure1": {
                        "stockStatus": "Low",
                        "uninterruptablePrice": 0.99,
                        "availableGpuCounts": None,
                    },
                }
            ]
        )

        offers = adapter.search()

        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].num_gpus, 1)
        self.assertEqual(offers[0].raw["cloud_type"], "SECURE")


class ServerHandlerTests(unittest.TestCase):
    def test_gpu_models_preview_uses_submitted_config(self):
        raw = config_to_dict(default_config())
        raw["platform"]["provider"] = "runpod"
        raw["credentials"]["runpod_api_key"] = "runpod-key"

        with patch("vast_autotools.server.platform_gpu_models") as platform_gpu_models_mock:
            platform_gpu_models_mock.return_value = {"models": [], "source": "runpod"}

            payload = RequestHandler._gpu_models_payload(_FakeHandlerContext(), config_from_dict(raw))

        self.assertEqual(payload["source"], "runpod")
        self.assertEqual(platform_gpu_models_mock.call_args.args[0].platform.provider, "runpod")


class SshCheckTests(unittest.TestCase):
    def test_ssh_check_requires_private_key_path(self):
        config = default_config()
        result = check_connection(SshTarget(host="example.invalid", port=22, user="root"), config.connection)

        self.assertFalse(result.ok)
        self.assertEqual(result.detail, "ssh private key path or private key is required")

    def test_ssh_check_rejects_missing_private_key_file(self):
        config = default_config()
        config.connection.ssh_private_key_path = "C:/definitely/not/found/id_ed25519"
        result = check_connection(SshTarget(host="example.invalid", port=22, user="root"), config.connection)

        self.assertFalse(result.ok)
        self.assertIn("ssh private key not found", result.detail)

    def test_ssh_check_writes_inline_private_key_to_temp_file(self):
        config = default_config()
        config.connection.ssh_private_key = "-----BEGIN OPENSSH PRIVATE KEY-----\ntest\n-----END OPENSSH PRIVATE KEY-----"
        captured = {}

        def fake_run(command, **kwargs):
            if command[0] == "icacls":
                class IcaclsCompleted:
                    returncode = 0
                    stdout = ""
                    stderr = ""

                return IcaclsCompleted()
            key_path = Path(command[command.index("-i") + 1])
            captured["key_path"] = key_path
            captured["key_text"] = key_path.read_text(encoding="utf-8")

            class Completed:
                returncode = 0
                stdout = ""
                stderr = ""

            return Completed()

        with patch("vast_autotools.ssh_check.subprocess.run", side_effect=fake_run):
            result = check_connection(SshTarget(host="example.invalid", port=22, user="root"), config.connection)

        self.assertTrue(result.ok)
        self.assertIn("BEGIN OPENSSH PRIVATE KEY", captured["key_text"])
        self.assertFalse(captured["key_path"].exists())


class _FakeNotifier:
    def __init__(self, sequence):
        self._sequence = sequence

    def send(self, message):
        self._sequence.append(("notify", message.title))


class _FakeSdk:
    def __init__(self, instances, templates=None):
        self._instances = instances
        self._templates = [] if templates is None else templates

    def show_instances(self):
        return self._instances

    def destroy_instance(self, id):
        return {"success": True, "id": id}

    def search_templates(self, query=None):
        return self._templates


class _FakeRunPodClient:
    def __init__(self, gpu_types=None, created_pod=None):
        self._gpu_types = [] if gpu_types is None else gpu_types
        self._created_pod = {"id": "podabc123"} if created_pod is None else created_pod
        self.last_create = None

    def gpu_types(self):
        return self._gpu_types

    def create_pod(self, payload):
        self.last_create = payload
        return self._created_pod


class _FakeHandlerContext:
    class _State:
        def add_event(self, level, message, data=None):
            return None

    state = _State()


def _auto_create_config(max_created_instances: int, max_creates_per_cycle: int):
    config = default_config()
    config.credentials.vast_api_key = "test-key"
    config.create.auto_create_enabled = True
    config.create.max_created_instances = max_created_instances
    config.create.max_creates_per_cycle = max_creates_per_cycle
    return config


def _scan_with_fakes(config, fake_adapter, notifier, with_private_key=False):
    with TemporaryDirectory() as tempdir:
        if with_private_key:
            key_path = Path(tempdir) / "id_ed25519"
            key_path.write_text("test-key", encoding="utf-8")
            config.connection.ssh_private_key_path = str(key_path)
        state = StateStore(Path(tempdir) / "events.json")
        service = MonitorService(state)
        with (
            patch("vast_autotools.monitor.build_adapter", side_effect=lambda current_config: fake_adapter(current_config)),
            patch("vast_autotools.monitor.build_notifier", return_value=notifier),
        ):
            return service._scan_with_config(config)


def _offer(offer_id: int) -> OfferView:
    return OfferView(offer_id, "RTX 4090", 1, 1.0, 100.0, 100.0, None, 24.0, "US", None, None, None, {})


if __name__ == "__main__":
    unittest.main()
