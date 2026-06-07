from __future__ import annotations

from typing import Protocol

from .config import AppConfig
from .runpod_adapter import RunPodAdapter
from .runpod_adapter import fallback_gpu_models as runpod_fallback_gpu_models
from .runpod_adapter import fetch_gpu_models as fetch_runpod_gpu_models
from .vast_adapter import CreateResult, FallbackGpuModels, InstanceReadyResult, OfferView, VastAdapter, fetch_gpu_models


class PlatformNotSupported(NotImplementedError):
    """Raised when a configured provider has no adapter implementation yet."""


class PlatformAdapter(Protocol):
    def search(self) -> list[OfferView]:
        ...

    def create_instance(self, offer: OfferView) -> CreateResult:
        ...

    def list_instances(self) -> list[dict]:
        ...

    def destroy_instance(self, instance_id: int | str) -> dict:
        ...

    def search_templates(self, keyword: str = "", limit: int = 60) -> list[dict]:
        ...

    def wait_for_connection(self, instance_id: int | str) -> InstanceReadyResult:
        ...


def platform_gpu_models(config: AppConfig) -> dict:
    if config.platform.provider == "vast":
        return fetch_gpu_models()
    if config.platform.provider == "runpod":
        return fetch_runpod_gpu_models(config.credentials.runpod_api_key)
    ensure_provider_supported(config)
    raise PlatformNotSupported(f"Unsupported provider: {config.platform.provider}")


def platform_fallback_gpu_models(config: AppConfig, error: Exception) -> dict:
    if config.platform.provider == "vast":
        return {
            "models": [{"name": name, "count": None} for name in FallbackGpuModels],
            "source": "fallback",
            "provider": "vast",
            "error": str(error),
        }
    if config.platform.provider == "runpod":
        return runpod_fallback_gpu_models(error)
    ensure_provider_supported(config)
    raise PlatformNotSupported(f"Unsupported provider: {config.platform.provider}")


def build_adapter(config: AppConfig) -> PlatformAdapter:
    ensure_provider_supported(config)
    if config.platform.provider == "vast":
        return VastAdapter(config)
    if config.platform.provider == "runpod":
        return RunPodAdapter(config)
    raise PlatformNotSupported(f"Unsupported provider: {config.platform.provider}")


def ensure_provider_supported(config: AppConfig) -> None:
    if config.platform.provider == "vast":
        return
    if config.platform.provider == "runpod":
        return
    raise PlatformNotSupported(f"Unsupported provider: {config.platform.provider}")
