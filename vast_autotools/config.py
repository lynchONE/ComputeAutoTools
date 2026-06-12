from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Literal, Optional, Union, get_args, get_origin, get_type_hints


ConfigPath = Path("data/config.json")


class ConfigError(ValueError):
    """Raised when user-supplied configuration is invalid."""


@dataclass
class CredentialsConfig:
    vast_api_key: str = ""
    runpod_api_key: str = ""
    bark_url: str = ""
    bark_group: str = "VastAutoTools"
    bark_sound: str = ""


@dataclass
class PlatformConfig:
    provider: Literal["vast", "runpod"] = "vast"


@dataclass
class UiConfig:
    language: Literal["zh", "en"] = "zh"


@dataclass
class SearchConfig:
    gpu_names: list[str] = field(default_factory=list)
    min_gpu_count: int = 1
    max_gpu_count: Optional[int] = None
    max_price_per_hour: Optional[float] = None
    min_total_flops: Optional[float] = None
    min_flops_per_usd: Optional[float] = None
    min_reliability: Optional[float] = None
    min_gpu_ram_gb: Optional[float] = None
    min_cuda_version: Optional[float] = None
    min_disk_space_gb: Optional[float] = None
    min_direct_ports: Optional[int] = None
    min_duration_days: Optional[float] = None
    geolocations_allow: list[str] = field(default_factory=list)
    geolocations_block: list[str] = field(default_factory=list)
    require_datacenter: Optional[bool] = None
    require_verified: bool = True
    allow_external: bool = False
    require_static_ip: Optional[bool] = None
    offer_type: Literal["on-demand", "bid", "reserved"] = "on-demand"
    order_by: Literal[
        "flops_per_usd",
        "dlperf_per_usd",
        "price",
        "total_flops",
        "reliability",
        "score",
    ] = "flops_per_usd"
    search_limit: int = 60
    pricing_storage_gb: float = 20.0


@dataclass
class CreateConfig:
    auto_create_enabled: bool = False
    allow_create_without_ssh_key: bool = False
    target_offer_ids: list[int] = field(default_factory=list)
    max_created_instances: int = 1
    max_creates_per_cycle: int = 1
    image: str = "pytorch/pytorch:2.4.1-cuda12.1-cudnn9-devel"
    disk_gb: float = 40.0
    label_prefix: str = "vast-auto"
    template_hash: str = ""
    runtype: Literal["ssh", "jupyter", "args"] = "ssh"
    args: str = ""
    docker_extra: str = ""
    onstart_cmd: str = ""
    env_vars: dict[str, str] = field(default_factory=dict)
    cancel_unavailable: bool = True
    jupyter_lab: bool = False


@dataclass
class ConnectionConfig:
    ssh_test_mode: Literal["ssh"] = "ssh"
    ssh_user: str = "root"
    ssh_private_key_path: str = ""
    ssh_private_key: str = ""
    ssh_command: str = "true"
    wait_timeout_seconds: int = 300
    poll_interval_seconds: int = 12
    connect_timeout_seconds: int = 8


@dataclass
class MonitorConfig:
    scan_interval_seconds: int = 60
    notify_on_error: bool = True
    stop_after_first_success: bool = False
    stock_alert_enabled: bool = False
    stock_alert_window_minutes: int = 60
    stock_alert_min_baseline_count: int = 5
    stock_alert_drop_count: int = 5
    stock_alert_drop_percent: float = 30.0
    stock_alert_cooldown_minutes: int = 60


@dataclass
class AppConfig:
    ui: UiConfig = field(default_factory=UiConfig)
    platform: PlatformConfig = field(default_factory=PlatformConfig)
    credentials: CredentialsConfig = field(default_factory=CredentialsConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    create: CreateConfig = field(default_factory=CreateConfig)
    connection: ConnectionConfig = field(default_factory=ConnectionConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)


def default_config() -> AppConfig:
    return AppConfig()


def config_to_dict(config: AppConfig) -> dict[str, Any]:
    return asdict(config)


def load_config(path: Path = ConfigPath) -> AppConfig:
    if not path.exists():
        return default_config()
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return config_from_dict(raw)


def save_config(config: AppConfig, path: Path = ConfigPath) -> None:
    validate_config(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(config_to_dict(config), handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    temp_path.replace(path)


def config_from_dict(raw: dict[str, Any]) -> AppConfig:
    if not isinstance(raw, dict):
        raise ConfigError("config must be a JSON object")
    _migrate_legacy_config(raw)
    config = _build_dataclass(AppConfig, raw, "config")
    validate_config(config)
    return config


def _migrate_legacy_config(raw: dict[str, Any]) -> None:
    connection = raw.get("connection")
    if not isinstance(connection, dict):
        return
    if connection.get("ssh_test_mode") == "tcp":
        connection["ssh_test_mode"] = "ssh"


def validate_config(config: AppConfig) -> None:
    config.search.gpu_names = normalize_gpu_names(config.search.gpu_names)
    search = config.search
    create = config.create
    connection = config.connection
    monitor = config.monitor
    platform = config.platform

    _require_int("search.min_gpu_count", search.min_gpu_count, minimum=1)
    _require_optional_int("search.max_gpu_count", search.max_gpu_count, minimum=1)
    if search.max_gpu_count is not None and search.max_gpu_count < search.min_gpu_count:
        raise ConfigError("search.max_gpu_count cannot be lower than search.min_gpu_count")
    _require_optional_float("search.max_price_per_hour", search.max_price_per_hour, minimum=0.0)
    _require_optional_float("search.min_total_flops", search.min_total_flops, minimum=0.0)
    _require_optional_float("search.min_flops_per_usd", search.min_flops_per_usd, minimum=0.0)
    _require_optional_float("search.min_reliability", search.min_reliability, minimum=0.0, maximum=1.0)
    _require_optional_float("search.min_gpu_ram_gb", search.min_gpu_ram_gb, minimum=0.0)
    _require_optional_float("search.min_cuda_version", search.min_cuda_version, minimum=0.0)
    _require_optional_float("search.min_disk_space_gb", search.min_disk_space_gb, minimum=0.0)
    _require_optional_int("search.min_direct_ports", search.min_direct_ports, minimum=0)
    _require_optional_float("search.min_duration_days", search.min_duration_days, minimum=0.0)
    _require_int("search.search_limit", search.search_limit, minimum=1, maximum=500)
    _require_float("search.pricing_storage_gb", search.pricing_storage_gb, minimum=1.0)

    _require_int("create.max_created_instances", create.max_created_instances, minimum=1)
    _require_int("create.max_creates_per_cycle", create.max_creates_per_cycle, minimum=1)
    _require_float("create.disk_gb", create.disk_gb, minimum=1.0)
    for offer_id in create.target_offer_ids:
        _require_int("create.target_offer_ids[]", offer_id, minimum=1)
    if create.auto_create_enabled:
        if platform.provider == "vast" and not config.credentials.vast_api_key.strip():
            raise ConfigError("Vast API Key is required before enabling auto create")
        if platform.provider == "runpod" and not config.credentials.runpod_api_key.strip():
            raise ConfigError("RunPod API Key is required before enabling auto create")
        if not create.image.strip() and not create.template_hash.strip():
            raise ConfigError("Docker image or template_hash is required before enabling auto create")
        if not create.label_prefix.strip():
            raise ConfigError("label_prefix is required before enabling auto create")

    _require_int("connection.wait_timeout_seconds", connection.wait_timeout_seconds, minimum=30)
    _require_int("connection.poll_interval_seconds", connection.poll_interval_seconds, minimum=2)
    _require_int("connection.connect_timeout_seconds", connection.connect_timeout_seconds, minimum=1)
    if not connection.ssh_command.strip():
        raise ConfigError("connection.ssh_command is required in ssh test mode")

    _require_int("monitor.scan_interval_seconds", monitor.scan_interval_seconds, minimum=15)
    _require_int("monitor.stock_alert_window_minutes", monitor.stock_alert_window_minutes, minimum=1)
    _require_int("monitor.stock_alert_min_baseline_count", monitor.stock_alert_min_baseline_count, minimum=1)
    _require_int("monitor.stock_alert_drop_count", monitor.stock_alert_drop_count, minimum=1)
    _require_float("monitor.stock_alert_drop_percent", monitor.stock_alert_drop_percent, minimum=0.0, maximum=100.0)
    _require_int("monitor.stock_alert_cooldown_minutes", monitor.stock_alert_cooldown_minutes, minimum=1)

    for key, value in create.env_vars.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ConfigError("create.env_vars keys and values must be strings")


def _build_dataclass(cls: type, raw: dict[str, Any], path: str):
    defaults = cls()
    type_hints = get_type_hints(cls)
    allowed = {item.name for item in fields(cls)}
    extra = set(raw) - allowed
    if extra:
        names = ", ".join(sorted(extra))
        raise ConfigError(f"{path} contains unknown fields: {names}")

    kwargs = {}
    for item in fields(cls):
        if item.name not in raw:
            kwargs[item.name] = getattr(defaults, item.name)
            continue
        value = raw[item.name]
        target = type_hints[item.name]
        if is_dataclass(target):
            if not isinstance(value, dict):
                raise ConfigError(f"{path}.{item.name} must be an object")
            kwargs[item.name] = _build_dataclass(target, value, f"{path}.{item.name}")
        else:
            kwargs[item.name] = _coerce_value(target, value, f"{path}.{item.name}")
    return cls(**kwargs)


def _coerce_value(target: Any, value: Any, path: str) -> Any:
    origin = get_origin(target)
    args = get_args(target)

    if origin is Union and type(None) in args:
        if value is None:
            return None
        inner = [arg for arg in args if arg is not type(None)]
        return _coerce_value(inner[0], value, path)

    if origin is Literal:
        if value not in args:
            allowed = ", ".join(str(item) for item in args)
            raise ConfigError(f"{path} must be one of: {allowed}")
        return value

    if origin is list:
        if not isinstance(value, list):
            raise ConfigError(f"{path} must be an array")
        item_type = args[0]
        return [_coerce_value(item_type, item, f"{path}[]") for item in value]

    if origin is dict:
        if not isinstance(value, dict):
            raise ConfigError(f"{path} must be an object")
        key_type, val_type = args
        return {
            _coerce_value(key_type, key, f"{path}.key"): _coerce_value(val_type, val, f"{path}.{key}")
            for key, val in value.items()
        }

    if target is bool:
        if not isinstance(value, bool):
            raise ConfigError(f"{path} must be a boolean")
        return value

    if target is int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConfigError(f"{path} must be an integer")
        return value

    if target is float:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ConfigError(f"{path} must be a number")
        return float(value)

    if target is str:
        if not isinstance(value, str):
            raise ConfigError(f"{path} must be a string")
        return value

    return value


def _require_int(name: str, value: int, minimum: int, maximum: Optional[int] = None) -> None:
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name} must be <= {maximum}")


def _require_optional_int(name: str, value: Optional[int], minimum: int) -> None:
    if value is None:
        return
    _require_int(name, value, minimum=minimum)


def _require_float(name: str, value: float, minimum: float, maximum: Optional[float] = None) -> None:
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name} must be <= {maximum}")


def _require_optional_float(
    name: str,
    value: Optional[float],
    minimum: float,
    maximum: Optional[float] = None,
) -> None:
    if value is None:
        return
    _require_float(name, value, minimum=minimum, maximum=maximum)


def normalize_gpu_names(names: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw_name in names:
        name = raw_name.strip()
        if not name:
            continue
        for item in _split_gpu_name(name):
            if item not in normalized:
                normalized.append(item)
    return normalized


def _split_gpu_name(name: str) -> list[str]:
    separators = [",", "，", "\n", ";", "；", "|"]
    chunks = [name]
    for separator in separators:
        next_chunks: list[str] = []
        for chunk in chunks:
            next_chunks.extend(part.strip() for part in chunk.split(separator))
        chunks = next_chunks

    result: list[str] = []
    for chunk in chunks:
        if not chunk:
            continue
        compact = " ".join(chunk.split())
        multi_rtx = _split_adjacent_rtx_models(compact)
        if multi_rtx:
            result.extend(multi_rtx)
        else:
            result.append(compact)
    return result


def _split_adjacent_rtx_models(value: str) -> list[str]:
    parts = value.split()
    if len(parts) < 4 or len(parts) % 2 != 0:
        return []
    result: list[str] = []
    for index in range(0, len(parts), 2):
        prefix = parts[index].upper()
        model = parts[index + 1]
        if prefix != "RTX" or not model:
            return []
        result.append(f"RTX {model}")
    return result
