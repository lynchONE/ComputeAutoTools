from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .config import AppConfig, ConfigError
from .ssh_check import check_connection
from .vast_adapter import CreateResult, InstanceReadyResult, OfferView, extract_ssh_target, offer_matches_config, sort_offers


RunPodRestBaseUrl = "https://rest.runpod.io/v1"
RunPodGraphqlUrl = "https://api.runpod.io/graphql"

FallbackGpuModels = [
    "RTX 3070",
    "RTX 3080",
    "RTX 3080 Ti",
    "RTX 3090",
    "RTX 3090 Ti",
    "RTX 4000 Ada",
    "RTX 4080",
    "RTX 4080 SUPER",
    "RTX 4090",
    "RTX 5000 Ada",
    "RTX 5080",
    "RTX 5090",
    "RTX 6000 Ada",
    "RTX A2000",
    "RTX A4000",
    "RTX A4500",
    "RTX A5000",
    "RTX A6000",
    "RTX PRO 6000 Blackwell",
    "A30",
    "A40",
    "A100 80GB PCIe",
    "A100-SXM4-80GB",
    "B200",
    "H100 80GB HBM3",
    "H100 NVL",
    "H100 PCIe",
    "H200",
    "H200 NVL",
    "L4",
    "L40",
    "L40S",
    "Tesla T4",
    "Tesla V100",
]


@dataclass
class _RunPodOffer:
    id: int
    gpu_type_id: str
    gpu_name: str
    gpu_count: int
    price_per_gpu: float
    stock_status: str
    raw: dict[str, Any]


class RunPodAdapter:
    def __init__(self, config: AppConfig):
        api_key = config.credentials.runpod_api_key.strip()
        if not api_key:
            raise ConfigError("RunPod API Key is empty; cannot call RunPod API")
        self.config = config
        self._client = RunPodClient(api_key)

    def search(self) -> list[OfferView]:
        gpu_types = self._client.gpu_types()
        offers = []
        for gpu_type in gpu_types:
            offers.extend(_gpu_type_to_offers(gpu_type, self.config.search))
        filtered = [offer for offer in offers if offer_matches_config(offer, self.config.search)]
        return sort_offers(filtered, self.config.search.order_by)

    def create_instance(self, offer: OfferView) -> CreateResult:
        runpod_offer = _runpod_offer_from_view(offer)
        create = self.config.create
        label = f"{create.label_prefix.strip()}-{int(time.time())}-{offer.id}"
        payload: dict[str, Any] = {
            "cloudType": runpod_offer.raw["cloud_type"],
            "computeType": "GPU",
            "gpuTypeIds": [runpod_offer.gpu_type_id],
            "gpuCount": runpod_offer.gpu_count,
            "gpuTypePriority": "custom",
            "containerDiskInGb": int(math.ceil(create.disk_gb)),
            "volumeInGb": int(math.ceil(self.config.search.pricing_storage_gb)),
            "volumeMountPath": "/workspace",
            "ports": ["22/tcp"],
            "supportPublicIp": True,
            "name": label,
            "env": dict(create.env_vars),
        }
        image = create.image.strip()
        template_id = create.template_hash.strip()
        if template_id:
            if _looks_like_vast_template_hash(template_id):
                if not image:
                    raise ConfigError("RunPod templateId looks like a Vast template_hash; clear it or select a RunPod template")
                payload["imageName"] = image
            else:
                payload["templateId"] = template_id
        elif image:
            payload["imageName"] = image
        else:
            raise ConfigError("Docker image or template_hash is required before enabling auto create")
        if create.args.strip():
            payload["dockerStartCmd"] = _split_command(create.args.strip())
        if create.onstart_cmd.strip():
            payload["dockerStartCmd"] = ["bash", "-lc", create.onstart_cmd.strip()]
        if self.config.search.min_cuda_version is not None:
            payload["allowedCudaVersions"] = [_format_cuda_version(self.config.search.min_cuda_version)]
        country_codes = [code.strip().upper() for code in self.config.search.geolocations_allow if code.strip()]
        if country_codes:
            payload["countryCodes"] = country_codes
        response = self._client.create_pod(payload)
        pod_id = response.get("id")
        if not isinstance(pod_id, str) or not pod_id.strip():
            raise RuntimeError("RunPod create pod response missing string id")
        normalized_response = _normalize_pod(response)
        return CreateResult(offer=offer, response=normalized_response, instance_id=pod_id.strip(), label=label)

    def count_managed_instances(self) -> int:
        label_prefix = self.config.create.label_prefix.strip()
        count = 0
        for instance in self.list_instances():
            label = instance.get("label")
            if isinstance(label, str) and label.startswith(label_prefix):
                count += 1
        return count

    def list_instances(self) -> list[dict[str, Any]]:
        pods = self._client.list_pods()
        return [_normalize_pod(pod) for pod in pods if isinstance(pod, dict)]

    def destroy_instance(self, instance_id: int | str) -> dict[str, Any]:
        return self._client.delete_pod(_instance_id_text(instance_id))

    def search_templates(self, keyword: str = "", limit: int = 60) -> list[dict[str, Any]]:
        templates = self._client.list_templates()
        rows = [_normalize_template(item) for item in templates if isinstance(item, dict)]
        if keyword.strip():
            key = keyword.strip().lower()
            rows = [
                item
                for item in rows
                if key in str(item.get("name") or "").lower()
                or key in str(item.get("image") or "").lower()
                or key in str(item.get("id") or "").lower()
            ]
        rows.sort(key=_template_sort_key)
        return rows[:limit]

    def wait_for_connection(self, instance_id: int | str) -> InstanceReadyResult:
        pod_id = _instance_id_text(instance_id)
        deadline = time.monotonic() + self.config.connection.wait_timeout_seconds
        last_detail = "pod has no SSH target yet"
        last_instance: dict[str, Any] = {}
        while time.monotonic() < deadline:
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                break
            try:
                instance = _normalize_pod(self._client.get_pod(pod_id))
            except Exception as exc:
                last_detail = f"get pod failed: {exc}"
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
        raise TimeoutError(f"SSH check timed out for RunPod pod {pod_id}: {last_detail}; {_instance_status_summary(last_instance)}")


class RunPodClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def gpu_types(self) -> list[dict[str, Any]]:
        query = """
        query {
          gpuTypes {
            id
            displayName
            memoryInGb
            secureCloud
            communityCloud
            secure1: lowestPrice(input: {gpuCount: 1, secureCloud: true}) {
              stockStatus
              uninterruptablePrice
              availableGpuCounts
            }
            secure2: lowestPrice(input: {gpuCount: 2, secureCloud: true}) {
              stockStatus
              uninterruptablePrice
              availableGpuCounts
            }
            secure4: lowestPrice(input: {gpuCount: 4, secureCloud: true}) {
              stockStatus
              uninterruptablePrice
              availableGpuCounts
            }
            secure8: lowestPrice(input: {gpuCount: 8, secureCloud: true}) {
              stockStatus
              uninterruptablePrice
              availableGpuCounts
            }
            community1: lowestPrice(input: {gpuCount: 1, secureCloud: false}) {
              stockStatus
              uninterruptablePrice
              availableGpuCounts
            }
            community2: lowestPrice(input: {gpuCount: 2, secureCloud: false}) {
              stockStatus
              uninterruptablePrice
              availableGpuCounts
            }
            community4: lowestPrice(input: {gpuCount: 4, secureCloud: false}) {
              stockStatus
              uninterruptablePrice
              availableGpuCounts
            }
            community8: lowestPrice(input: {gpuCount: 8, secureCloud: false}) {
              stockStatus
              uninterruptablePrice
              availableGpuCounts
            }
          }
        }
        """
        payload = self.graphql(query)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("RunPod gpuTypes response missing data object")
        gpu_types = data.get("gpuTypes")
        if not isinstance(gpu_types, list):
            raise RuntimeError("RunPod gpuTypes did not return a list")
        return [item for item in gpu_types if isinstance(item, dict)]

    def create_pod(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.rest("POST", "/pods", payload)
        if not isinstance(response, dict):
            raise RuntimeError("RunPod create pod did not return an object")
        return response

    def list_pods(self) -> list[dict[str, Any]]:
        response = self.rest("GET", "/pods")
        if not isinstance(response, list):
            raise RuntimeError("RunPod list pods did not return a list")
        return [item for item in response if isinstance(item, dict)]

    def get_pod(self, pod_id: str) -> dict[str, Any]:
        response = self.rest("GET", f"/pods/{pod_id}")
        if not isinstance(response, dict):
            raise RuntimeError("RunPod get pod did not return an object")
        return response

    def delete_pod(self, pod_id: str) -> dict[str, Any]:
        response = self.rest("DELETE", f"/pods/{pod_id}")
        if response is None:
            return {"success": True, "id": pod_id}
        if not isinstance(response, dict):
            raise RuntimeError("RunPod delete pod did not return an object")
        response["success"] = True
        return response

    def list_templates(self) -> list[dict[str, Any]]:
        query = {
            "includePublicTemplates": "true",
            "includeRunpodTemplates": "true",
        }
        response = self.rest("GET", f"/templates?{urlencode(query)}")
        if not isinstance(response, list):
            raise RuntimeError("RunPod list templates did not return a list")
        return [item for item in response if isinstance(item, dict)]

    def graphql(self, query: str, variables: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": query}
        if variables is not None:
            payload["variables"] = variables
        response = _json_request(
            "POST",
            f"{RunPodGraphqlUrl}?{urlencode({'api_key': self.api_key})}",
            self.api_key,
            payload,
            auth_header=False,
        )
        if not isinstance(response, dict):
            raise RuntimeError("RunPod GraphQL response was not an object")
        errors = response.get("errors")
        if errors:
            raise RuntimeError(f"RunPod GraphQL failed: {json.dumps(errors, ensure_ascii=False)}")
        return response

    def rest(self, method: str, path: str, payload: Optional[dict[str, Any]] = None) -> Any:
        return _json_request(method, f"{RunPodRestBaseUrl}{path}", self.api_key, payload)


def fetch_gpu_models(api_key: str) -> dict[str, Any]:
    client = RunPodClient(api_key.strip())
    models = []
    for row in client.gpu_types():
        name = row.get("displayName")
        if not isinstance(name, str) or not name.strip():
            continue
        models.append({"name": name.strip(), "count": _max_stock_count(row)})
    models.sort(key=lambda item: item["name"])
    return {"models": models, "source": "runpod", "provider": "runpod"}


def fallback_gpu_models(error: Exception) -> dict[str, Any]:
    return {
        "models": [{"name": name, "count": None} for name in FallbackGpuModels],
        "source": "fallback",
        "provider": "runpod",
        "error": str(error),
    }


def _json_request(method: str, url: str, api_key: str, payload: Optional[dict[str, Any]], auth_header: bool = True) -> Any:
    headers = {
        "Accept": "application/json",
        "User-Agent": "VastAutoTools/1.0 (+https://runpod.io)",
    }
    if auth_header:
        headers["Authorization"] = f"Bearer {api_key}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read()
            if not body:
                return None
            return json.loads(body.decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        detail = body.strip()
        if detail:
            raise RuntimeError(f"RunPod API {method} {_redact_url(url)} failed with HTTP {exc.code}: {detail}") from exc
        raise RuntimeError(f"RunPod API {method} {_redact_url(url)} failed with HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"RunPod API {method} {_redact_url(url)} failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"RunPod API {method} {_redact_url(url)} returned invalid JSON") from exc


def _gpu_type_to_offers(raw: dict[str, Any], search) -> list[OfferView]:
    gpu_type_id = raw.get("id")
    display_name = raw.get("displayName")
    if not isinstance(gpu_type_id, str) or not gpu_type_id.strip():
        return []
    if not isinstance(display_name, str) or not display_name.strip():
        return []
    if not _gpu_name_allowed(gpu_type_id, display_name, search.gpu_names):
        return []
    clouds: list[tuple[str, dict[int, Any]]] = []
    if search.require_datacenter is not False:
        clouds.append(("SECURE", {1: raw.get("secure1"), 2: raw.get("secure2"), 4: raw.get("secure4"), 8: raw.get("secure8")}))
    if search.require_datacenter is not True:
        clouds.append(("COMMUNITY", {1: raw.get("community1"), 2: raw.get("community2"), 4: raw.get("community4"), 8: raw.get("community8")}))
    offers = []
    for cloud_type, price_by_count in clouds:
        for gpu_count, lowest_price in price_by_count.items():
            if not isinstance(lowest_price, dict):
                continue
            offer = _gpu_type_cloud_to_offer(raw, gpu_type_id.strip(), display_name.strip(), cloud_type, gpu_count, lowest_price, search)
            if offer is not None:
                offers.append(offer)
    return offers


def _gpu_type_cloud_to_offer(
    raw: dict[str, Any],
    gpu_type_id: str,
    display_name: str,
    cloud_type: str,
    gpu_count: int,
    lowest_price: dict[str, Any],
    search,
) -> Optional[OfferView]:
    price_per_gpu = _as_float(lowest_price.get("uninterruptablePrice"))
    if price_per_gpu is None or price_per_gpu <= 0:
        return None
    if gpu_count < search.min_gpu_count:
        return None
    if search.max_gpu_count is not None and gpu_count > search.max_gpu_count:
        return None
    if _stock_status(lowest_price.get("stockStatus")) == "none":
        return None
    gpu_name = display_name
    dph_total = price_per_gpu * gpu_count
    total_flops = _estimated_total_flops(gpu_name, gpu_count)
    flops_per_usd = total_flops / dph_total
    if not math.isfinite(flops_per_usd):
        return None
    runpod_offer = _RunPodOffer(
        id=_stable_offer_id(gpu_type_id, gpu_count, cloud_type),
        gpu_type_id=gpu_type_id,
        gpu_name=gpu_name,
        gpu_count=gpu_count,
        price_per_gpu=price_per_gpu,
        stock_status=str(lowest_price.get("stockStatus") or ""),
        raw=raw,
    )
    raw_offer = {
        "provider": "runpod",
        "gpu_type_id": runpod_offer.gpu_type_id,
        "cloud_type": cloud_type,
        "gpu_name": gpu_name,
        "gpu_count": gpu_count,
        "price_per_gpu": price_per_gpu,
        "stock_status": runpod_offer.stock_status,
        "gpu_type": raw,
    }
    return OfferView(
        id=runpod_offer.id,
        gpu_name=gpu_name,
        num_gpus=gpu_count,
        dph_total=dph_total,
        total_flops=total_flops,
        flops_per_usd=flops_per_usd,
        reliability=_stock_reliability(runpod_offer.stock_status),
        gpu_ram_gb=_as_float(raw.get("memoryInGb")),
        geolocation="RunPod",
        machine_id=None,
        host_id=None,
        score=_stock_reliability(runpod_offer.stock_status),
        raw=raw_offer,
    )


def _runpod_offer_from_view(offer: OfferView) -> _RunPodOffer:
    raw = offer.raw
    gpu_type_id = raw.get("gpu_type_id")
    price_per_gpu = _as_float(raw.get("price_per_gpu"))
    stock_status = raw.get("stock_status")
    cloud_type = raw.get("cloud_type")
    if not isinstance(gpu_type_id, str) or not gpu_type_id.strip():
        raise RuntimeError("RunPod offer missing gpu_type_id")
    if cloud_type not in {"SECURE", "COMMUNITY"}:
        raise RuntimeError("RunPod offer missing cloud_type")
    if price_per_gpu is None or price_per_gpu <= 0:
        raise RuntimeError("RunPod offer missing price_per_gpu")
    return _RunPodOffer(
        id=offer.id,
        gpu_type_id=gpu_type_id.strip(),
        gpu_name=offer.gpu_name,
        gpu_count=offer.num_gpus,
        price_per_gpu=price_per_gpu,
        stock_status=str(stock_status or ""),
        raw=raw,
    )


def _normalize_pod(pod: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(pod)
    pod_id = pod.get("id")
    if isinstance(pod_id, str) and pod_id.strip():
        normalized["instance_id"] = pod_id.strip()
    name = pod.get("name")
    if isinstance(name, str):
        normalized["label"] = name
    gpu = pod.get("gpu")
    machine = pod.get("machine")
    if isinstance(gpu, dict):
        gpu_name = gpu.get("displayName") or gpu.get("id")
        gpu_count = _as_int(gpu.get("count"))
    elif isinstance(machine, dict):
        gpu_name = machine.get("gpuDisplayName") or machine.get("gpuTypeId")
        gpu_count = _as_int(machine.get("minPodGpuCount"))
    else:
        gpu_name = None
        gpu_count = None
    if isinstance(gpu_name, str) and gpu_name.strip():
        normalized["gpu_name"] = gpu_name.strip()
    if gpu_count is not None:
        normalized["num_gpus"] = gpu_count
    price = _as_float(pod.get("adjustedCostPerHr"))
    if price is None:
        price = _as_float(pod.get("costPerHr"))
    if price is not None:
        normalized["dph_total"] = price
    machine_location = machine.get("location") if isinstance(machine, dict) else None
    data_center = machine.get("dataCenterId") if isinstance(machine, dict) else None
    if isinstance(machine_location, str) and machine_location.strip():
        normalized["geolocation"] = machine_location.strip()
    elif isinstance(data_center, str) and data_center.strip():
        normalized["geolocation"] = data_center.strip()
    status = pod.get("desiredStatus")
    if isinstance(status, str):
        normalized["actual_status"] = status.lower()
        normalized["cur_state"] = status.lower()
    last_status = pod.get("lastStatusChange")
    if isinstance(last_status, str):
        normalized["status_msg"] = last_status
    public_ip = pod.get("publicIp")
    if isinstance(public_ip, str) and public_ip.strip():
        normalized["public_ipaddr"] = public_ip.strip()
        normalized["ssh_host"] = public_ip.strip()
    port = _extract_ssh_port(pod)
    if port is not None:
        normalized["ssh_port"] = port
    start_time = _parse_runpod_time(pod.get("lastStartedAt"))
    if start_time is not None:
        normalized["start_date"] = start_time
    return normalized


def _normalize_template(template: dict[str, Any]) -> dict[str, Any]:
    item = dict(template)
    template_id = template.get("id")
    if isinstance(template_id, str):
        item["hash_id"] = template_id
    image = template.get("imageName")
    if isinstance(image, str):
        item["image"] = image
    item["recommended"] = template.get("isRunpod") is True
    item["private"] = template.get("isPublic") is not True
    return item


def _extract_ssh_port(pod: dict[str, Any]) -> Optional[int]:
    port_mappings = pod.get("portMappings")
    if isinstance(port_mappings, dict):
        port = port_mappings.get("22")
        if port is None:
            port = port_mappings.get(22)
        parsed = _as_int(port)
        if parsed is not None and parsed > 0:
            return parsed
    runtime = pod.get("runtime")
    if isinstance(runtime, dict):
        ports = runtime.get("ports")
        if isinstance(ports, list):
            for item in ports:
                if not isinstance(item, dict):
                    continue
                private_port = _as_int(item.get("privatePort"))
                if private_port != 22:
                    continue
                public_port = _as_int(item.get("publicPort"))
                if public_port is not None and public_port > 0:
                    return public_port
    return None


def _estimated_total_flops(gpu_name: str, gpu_count: int) -> float:
    name = gpu_name.upper()
    per_gpu = 1.0
    known = {
        "RTX 5090": 104.8,
        "RTX 4090": 82.6,
        "RTX 4080": 48.7,
        "RTX 3090": 35.6,
        "RTX 3080": 29.8,
        "H200": 67.0,
        "H100": 67.0,
        "A100": 19.5,
        "L40S": 91.6,
        "L40": 90.5,
        "L4": 30.3,
        "A40": 37.4,
        "A30": 10.3,
        "A6000": 38.7,
        "A5000": 27.8,
        "A4000": 19.2,
        "T4": 8.1,
        "V100": 14.1,
    }
    for key, value in known.items():
        if key in name:
            per_gpu = value
            break
    return per_gpu * gpu_count


def _stable_offer_id(gpu_type_id: str, gpu_count: int, cloud_type: str) -> int:
    digest = hashlib.sha256(f"runpod:{gpu_type_id}:{gpu_count}:{cloud_type}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF or 1


def _stock_status(value: Any) -> str:
    return str(value or "").strip().lower()


def _stock_reliability(value: Any) -> Optional[float]:
    status = _stock_status(value)
    if status == "high":
        return 1.0
    if status == "medium":
        return 0.7
    if status == "low":
        return 0.35
    if status == "none":
        return 0.0
    return None


def _stock_count(value: Any) -> Optional[int]:
    status = _stock_status(value)
    if status == "high":
        return 100
    if status == "medium":
        return 10
    if status == "low":
        return 1
    if status == "none":
        return 0
    return None


def _max_stock_count(row: dict[str, Any]) -> Optional[int]:
    counts = [
        _stock_count(value.get("stockStatus"))
        for key in ("secure1", "secure2", "secure4", "secure8", "community1", "community2", "community4", "community8")
        if isinstance((value := row.get(key)), dict)
    ]
    known_counts = [count for count in counts if count is not None]
    if not known_counts:
        return None
    return max(known_counts)


def _format_cuda_version(value: float) -> str:
    return f"{value:.1f}"


def _looks_like_vast_template_hash(value: str) -> bool:
    text = value.strip()
    return len(text) == 32 and all(character in "0123456789abcdefABCDEF" for character in text)


def _split_command(value: str) -> list[str]:
    parts = value.split()
    if parts:
        return parts
    raise ConfigError("create.args cannot be empty after parsing")


def _instance_id_text(instance_id: int | str) -> str:
    if isinstance(instance_id, int) and not isinstance(instance_id, bool):
        return str(instance_id)
    if isinstance(instance_id, str) and instance_id.strip():
        return instance_id.strip()
    raise ValueError("instance_id must be a non-empty string or integer")


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
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


def _parse_runpod_time(value: Any) -> Optional[float]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _instance_status_summary(instance: dict[str, Any]) -> str:
    if not instance:
        return "last_status=unavailable"
    fields = ["desiredStatus", "actual_status", "cur_state", "status_msg"]
    parts = []
    for field in fields:
        value = instance.get(field)
        if value is None:
            continue
        parts.append(f"{field}={value}")
    if not parts:
        return "last_status=unknown"
    return "; ".join(str(part) for part in parts)


def _template_sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
    recommended = 0 if item.get("recommended") is True else 1
    private = 0 if item.get("private") is True else 1
    return (recommended, private, str(item.get("name") or ""))


def _gpu_name_allowed(gpu_type_id: str, display_name: str, configured_names: list[str]) -> bool:
    if not configured_names:
        return True
    haystacks = [_normalize_gpu_name(gpu_type_id), _normalize_gpu_name(display_name)]
    for configured_name in configured_names:
        needle = _normalize_gpu_name(configured_name)
        if not needle:
            continue
        if any(needle in haystack for haystack in haystacks):
            return True
    return False


def _normalize_gpu_name(value: str) -> str:
    return " ".join(value.upper().replace("NVIDIA", "").replace("GEFORCE", "").split())


def _redact_url(url: str) -> str:
    split = urlsplit(url)
    query = urlencode([(key, "redacted" if key.lower() == "api_key" else value) for key, value in parse_qsl(split.query, keep_blank_values=True)])
    return urlunsplit((split.scheme, split.netloc, split.path, query, split.fragment))
