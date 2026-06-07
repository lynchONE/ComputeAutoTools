from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from typing import Any, Optional

from .config import AppConfig, ConfigError, SearchConfig
from .ssh_check import ConnectionCheckResult, SshTarget, check_connection


FallbackGpuModels = [
    "A100 PCIE",
    "A100 SXM4",
    "A10g",
    "B200",
    "H100 NVL",
    "H100 PCIE",
    "H100 SXM",
    "H200",
    "H200 NVL",
    "L4",
    "L40",
    "L40S",
    "RTX 3090",
    "RTX 3090 Ti",
    "RTX 4090",
    "RTX 4090D",
    "RTX 5090",
    "RTX A4000",
    "RTX A5000",
    "RTX A6000",
    "RTX PRO 5000",
    "RTX PRO 6000 S",
    "RTX PRO 6000 WS",
    "Tesla T4",
    "Tesla V100",
]


@dataclass
class OfferView:
    id: int
    gpu_name: str
    num_gpus: int
    dph_total: float
    total_flops: float
    flops_per_usd: float
    reliability: Optional[float]
    gpu_ram_gb: Optional[float]
    geolocation: str
    machine_id: Optional[int]
    host_id: Optional[int]
    score: Optional[float]
    raw: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "gpu_name": self.gpu_name,
            "num_gpus": self.num_gpus,
            "dph_total": self.dph_total,
            "total_flops": self.total_flops,
            "flops_per_usd": self.flops_per_usd,
            "reliability": self.reliability,
            "gpu_ram_gb": self.gpu_ram_gb,
            "geolocation": self.geolocation,
            "machine_id": self.machine_id,
            "host_id": self.host_id,
            "score": self.score,
            "raw": self.raw,
        }


@dataclass
class CreateResult:
    offer: OfferView
    response: dict[str, Any]
    instance_id: int | str
    label: str


@dataclass
class InstanceReadyResult:
    instance: dict[str, Any]
    target: SshTarget
    check: ConnectionCheckResult


class VastAdapter:
    def __init__(self, config: AppConfig):
        if not config.credentials.vast_api_key.strip():
            raise ConfigError("Vast API Key is empty; cannot call Vast SDK")
        self.config = config
        self._sdk = self._build_sdk(config.credentials.vast_api_key.strip())

    def search(self) -> list[OfferView]:
        query = build_search_query(self.config.search)
        order = build_order(self.config.search.order_by)
        raw_offers = self._sdk.search_offers(
            query=query,
            type=self.config.search.offer_type,
            order=order,
            limit=self.config.search.search_limit,
            storage=self.config.search.pricing_storage_gb,
            no_default=True,
        )
        if not isinstance(raw_offers, list):
            raise RuntimeError("Vast search_offers did not return a list")
        offers = [offer for offer in (_offer_to_view(item) for item in raw_offers) if offer is not None]
        filtered = [offer for offer in offers if offer_matches_config(offer, self.config.search)]
        return sort_offers(filtered, self.config.search.order_by)

    def create_instance(self, offer: OfferView) -> CreateResult:
        create = self.config.create
        label = f"{create.label_prefix.strip()}-{int(time.time())}-{offer.id}"
        kwargs: dict[str, Any] = {
            "id": offer.id,
            "image": _empty_to_none(create.image),
            "disk": create.disk_gb,
            "label": label,
            "env": dict(create.env_vars),
            "extra": _empty_to_none(create.docker_extra),
            "onstart_cmd": _empty_to_none(create.onstart_cmd),
            "template_hash": _empty_to_none(create.template_hash),
            "runtype": create.runtype,
            "args": _empty_to_none(create.args),
            "cancel_unavail": create.cancel_unavailable,
            "jupyter_lab": create.jupyter_lab,
        }
        response = self._sdk.create_instance(**kwargs)
        if not isinstance(response, dict):
            raise RuntimeError("Vast create_instance did not return an object")
        if response.get("success") is not True:
            raise RuntimeError(f"Vast create_instance failed: {json.dumps(response, ensure_ascii=False)}")
        new_contract = response.get("new_contract")
        if not isinstance(new_contract, int):
            raise RuntimeError("Vast create_instance response missing integer new_contract")
        return CreateResult(offer=offer, response=response, instance_id=new_contract, label=label)

    def count_managed_instances(self) -> int:
        label_prefix = self.config.create.label_prefix.strip()
        instances = self.list_instances()
        count = 0
        for instance in instances:
            label = instance.get("label")
            if isinstance(label, str) and label.startswith(label_prefix):
                count += 1
        return count

    def list_instances(self) -> list[dict[str, Any]]:
        instances = self._sdk.show_instances()
        if not isinstance(instances, list):
            raise RuntimeError("Vast show_instances did not return a list")
        return [instance for instance in instances if isinstance(instance, dict)]

    def destroy_instance(self, instance_id: int) -> dict[str, Any]:
        response = self._sdk.destroy_instance(id=instance_id)
        if not isinstance(response, dict):
            raise RuntimeError("Vast destroy_instance did not return an object")
        return response

    def search_templates(self, keyword: str = "", limit: int = 60) -> list[dict[str, Any]]:
        query: dict[str, Any] = {}
        templates = self._sdk.search_templates(query=query)
        if not isinstance(templates, list):
            raise RuntimeError("Vast search_templates did not return a list")
        rows = [item for item in templates if isinstance(item, dict)]
        if keyword.strip():
            key = keyword.strip().lower()
            rows = [
                item
                for item in rows
                if key in str(item.get("name") or "").lower()
                or key in str(item.get("image") or "").lower()
                or key in str(item.get("tag") or "").lower()
            ]
        rows.sort(key=_template_sort_key)
        return rows[:limit]

    def wait_for_connection(self, instance_id: int) -> InstanceReadyResult:
        deadline = time.monotonic() + self.config.connection.wait_timeout_seconds
        last_detail = "instance has no SSH target yet"
        last_instance: dict[str, Any] = {}
        while time.monotonic() < deadline:
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                break
            try:
                instance = self._sdk.show_instance(instance_id)
            except Exception as exc:
                last_detail = f"show_instance failed: {exc}"
                time.sleep(min(self.config.connection.poll_interval_seconds, max(0.0, deadline - time.monotonic())))
                continue
            if not isinstance(instance, dict):
                last_detail = "Vast show_instance did not return an object"
                time.sleep(min(self.config.connection.poll_interval_seconds, max(0.0, deadline - time.monotonic())))
                continue
            last_instance = instance
            target = extract_ssh_target(instance, self.config.connection.ssh_user)
            if target is not None:
                check = check_connection(target, self.config.connection, max(0.0, deadline - time.monotonic()))
                last_detail = check.detail
                if check.ok:
                    return InstanceReadyResult(instance=instance, target=target, check=check)
            time.sleep(min(self.config.connection.poll_interval_seconds, max(0.0, deadline - time.monotonic())))
        status_summary = _instance_status_summary(last_instance)
        raise TimeoutError(f"SSH check timed out for instance {instance_id}: {last_detail}; {status_summary}")

    @staticmethod
    def _build_sdk(api_key: str):
        try:
            from vastai import VastAI
        except ImportError as exc:
            raise RuntimeError("Missing vastai dependency. Run: py -m pip install -r requirements.txt") from exc
        return VastAI(api_key=api_key, raw=True, quiet=True)


def fetch_gpu_models(limit: int = 500) -> dict[str, Any]:
    try:
        from vastai.api.client import VastClient
        from vastai.api.offers import search_offers
    except ImportError as exc:
        raise RuntimeError("Missing vastai dependency. Run: py -m pip install -r requirements.txt") from exc

    client = VastClient(api_key=None, retry=2)
    query = {"rentable": {"eq": True}, "rented": {"eq": False}}
    rows = search_offers(
        client,
        query=query,
        order=[["gpu_name", "asc"]],
        limit=limit,
        storage=20,
        no_default=True,
    )
    if not isinstance(rows, list):
        raise RuntimeError("Vast GPU model lookup did not return a list")

    counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        gpu_name = row.get("gpu_name")
        if not isinstance(gpu_name, str) or not gpu_name.strip():
            continue
        name = gpu_name.strip()
        counts[name] = counts.get(name, 0) + 1

    models = [{"name": name, "count": counts[name]} for name in sorted(counts)]
    return {"models": models, "source": "vast", "total_offers_sampled": len(rows)}


def build_search_query(search: SearchConfig) -> str:
    parts = ["rentable=True", "rented=False"]
    if search.require_verified:
        parts.append("verified=True")
    if not search.allow_external:
        parts.append("external=False")

    if search.gpu_names:
        encoded = [_encode_gpu_name(name) for name in search.gpu_names if name.strip()]
        if len(encoded) == 1:
            parts.append(f"gpu_name={encoded[0]}")
        elif encoded:
            joined = ",".join(f'"{name.replace("_", " ")}"' for name in encoded)
            parts.append(f"gpu_name in [{joined}]")

    parts.append(f"num_gpus>={search.min_gpu_count}")
    if search.max_gpu_count is not None:
        parts.append(f"num_gpus<={search.max_gpu_count}")
    if search.max_price_per_hour is not None:
        parts.append(f"dph<={search.max_price_per_hour}")
    if search.min_total_flops is not None:
        parts.append(f"total_flops>={search.min_total_flops}")
    if search.min_flops_per_usd is not None:
        parts.append(f"flops_usd>={search.min_flops_per_usd}")
    if search.min_reliability is not None:
        parts.append(f"reliability>={search.min_reliability}")
    if search.min_gpu_ram_gb is not None:
        parts.append(f"gpu_ram>={search.min_gpu_ram_gb}")
    if search.min_cuda_version is not None:
        parts.append(f"cuda_vers>={search.min_cuda_version}")
    if search.min_disk_space_gb is not None:
        parts.append(f"disk_space>={search.min_disk_space_gb}")
    if search.min_direct_ports is not None:
        parts.append(f"direct_port_count>={search.min_direct_ports}")
    if search.min_duration_days is not None:
        parts.append(f"duration>={search.min_duration_days}")
    if search.geolocations_allow:
        parts.append(f"geolocation in [{_join_codes(search.geolocations_allow)}]")
    if search.geolocations_block:
        parts.append(f"geolocation notin [{_join_codes(search.geolocations_block)}]")
    if search.require_datacenter is not None:
        parts.append(f"datacenter={search.require_datacenter}")
    if search.require_static_ip is not None:
        parts.append(f"static_ip={search.require_static_ip}")
    return " ".join(parts)


def build_order(order_by: str) -> str:
    mapping = {
        "flops_per_usd": "flops_usd-",
        "dlperf_per_usd": "dlperf_usd-",
        "price": "dph",
        "total_flops": "total_flops-",
        "reliability": "reliability-",
        "score": "score-",
    }
    if order_by not in mapping:
        raise ConfigError(f"Unknown order field: {order_by}")
    return mapping[order_by]


def offer_matches_config(offer: OfferView, search: SearchConfig) -> bool:
    if search.max_price_per_hour is not None and offer.dph_total > search.max_price_per_hour:
        return False
    if search.min_total_flops is not None and offer.total_flops < search.min_total_flops:
        return False
    if search.min_flops_per_usd is not None and offer.flops_per_usd < search.min_flops_per_usd:
        return False
    if search.min_reliability is not None:
        if offer.reliability is None or offer.reliability < search.min_reliability:
            return False
    if search.min_gpu_ram_gb is not None:
        if offer.gpu_ram_gb is None or offer.gpu_ram_gb < search.min_gpu_ram_gb:
            return False
    return True


def sort_offers(offers: list[OfferView], order_by: str) -> list[OfferView]:
    if order_by == "price":
        return sorted(offers, key=lambda item: item.dph_total)
    if order_by == "total_flops":
        return sorted(offers, key=lambda item: item.total_flops, reverse=True)
    if order_by == "reliability":
        return sorted(offers, key=lambda item: _score_optional(item.reliability), reverse=True)
    if order_by == "score":
        return sorted(offers, key=lambda item: _score_optional(item.score), reverse=True)
    return sorted(offers, key=lambda item: item.flops_per_usd, reverse=True)


def extract_ssh_target(instance: dict[str, Any], user: str) -> Optional[SshTarget]:
    host = instance.get("ssh_host")
    if not isinstance(host, str) or not host.strip():
        public_ip = instance.get("public_ipaddr")
        if isinstance(public_ip, str) and public_ip.strip():
            host = public_ip
    if not isinstance(host, str) or not host.strip():
        public_ip = instance.get("publicIp")
        if isinstance(public_ip, str) and public_ip.strip():
            host = public_ip
    port = instance.get("ssh_port")
    if not isinstance(port, int):
        port = _extract_port_from_ports(instance.get("ports"))
    if not isinstance(port, int):
        port = _extract_port_from_mapping(instance.get("portMappings"))
    if isinstance(host, str) and host.strip() and isinstance(port, int) and port > 0:
        return SshTarget(host=host.strip(), port=port, user=user)
    return None


def _extract_port_from_ports(value: Any) -> Optional[int]:
    ports = value
    if isinstance(value, str) and value.strip():
        try:
            ports = json.loads(value)
        except json.JSONDecodeError:
            return None
    if not isinstance(ports, dict):
        return None
    entry = ports.get("22/tcp")
    if not isinstance(entry, list) or not entry:
        return None
    first = entry[0]
    if not isinstance(first, dict):
        return None
    host_port = first.get("HostPort")
    if isinstance(host_port, int):
        return host_port
    if isinstance(host_port, str) and host_port.isdigit():
        return int(host_port)
    return None


def _extract_port_from_mapping(value: Any) -> Optional[int]:
    if not isinstance(value, dict):
        return None
    port = value.get("22")
    if port is None:
        port = value.get(22)
    if isinstance(port, int) and not isinstance(port, bool):
        return port
    if isinstance(port, str) and port.isdigit():
        return int(port)
    return None


def _instance_status_summary(instance: dict[str, Any]) -> str:
    if not instance:
        return "last_status=unavailable"
    fields = ["actual_status", "cur_state", "next_state", "intended_status", "status_msg"]
    parts = []
    for field in fields:
        value = instance.get(field)
        if value is None:
            continue
        parts.append(f"{field}={value}")
    if not parts:
        return "last_status=unknown"
    return "; ".join(str(part) for part in parts)


def _offer_to_view(raw: Any) -> Optional[OfferView]:
    if not isinstance(raw, dict):
        return None
    offer_id = _as_int(raw.get("id"))
    dph_total = _as_float(raw.get("dph_total"))
    total_flops = _as_float(raw.get("total_flops"))
    gpu_name = raw.get("gpu_name")
    num_gpus = _as_int(raw.get("num_gpus"))
    if offer_id is None or dph_total is None or total_flops is None or num_gpus is None:
        return None
    if not isinstance(gpu_name, str) or not gpu_name.strip():
        return None
    if dph_total <= 0 or total_flops < 0:
        return None
    flops_per_usd = total_flops / dph_total
    if not math.isfinite(flops_per_usd):
        return None
    return OfferView(
        id=offer_id,
        gpu_name=gpu_name,
        num_gpus=num_gpus,
        dph_total=dph_total,
        total_flops=total_flops,
        flops_per_usd=flops_per_usd,
        reliability=_as_float(raw.get("reliability")),
        gpu_ram_gb=_gpu_ram_to_gb(raw.get("gpu_ram")),
        geolocation=str(raw.get("geolocation")) if raw.get("geolocation") is not None else "",
        machine_id=_as_int(raw.get("machine_id")),
        host_id=_as_int(raw.get("host_id")),
        score=_as_float(raw.get("score")),
        raw=raw,
    )


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _gpu_ram_to_gb(value: Any) -> Optional[float]:
    ram = _as_float(value)
    if ram is None:
        return None
    if ram > 256:
        return ram / 1000.0
    return ram


def _encode_gpu_name(name: str) -> str:
    return name.strip().replace(" ", "_")


def _join_codes(codes: list[str]) -> str:
    return ",".join(code.strip().upper() for code in codes if code.strip())


def _empty_to_none(value: str) -> Optional[str]:
    stripped = value.strip()
    if not stripped:
        return None
    return stripped


def _score_optional(value: Optional[float]) -> float:
    if value is None:
        return -1.0
    return value


def _template_sort_key(item: dict[str, Any]) -> tuple[int, int, int, str]:
    recommended = 0 if item.get("recommended") is True else 1
    private = 0 if item.get("private") is True else 1
    count_created = item.get("count_created")
    popularity = -count_created if isinstance(count_created, int) and not isinstance(count_created, bool) else 0
    return (recommended, private, popularity, str(item.get("name") or ""))
