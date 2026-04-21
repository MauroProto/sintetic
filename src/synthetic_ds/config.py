from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class ProviderProfile(BaseModel):
    api_key_env: str
    base_url: str
    model: str
    max_tokens: int = 2048
    temperature: float = 0.2
    concurrency: int = 4
    extra_headers: dict[str, str] = Field(default_factory=dict)


def default_provider_profiles() -> dict[str, ProviderProfile]:
    return {
        "fireworks": ProviderProfile(
            api_key_env="FIREWORKS_API_KEY",
            base_url="https://api.fireworks.ai/inference/v1",
            model="accounts/fireworks/routers/kimi-k2p5-turbo",
        ),
        "openai": ProviderProfile(
            api_key_env="OPENAI_API_KEY",
            base_url="https://api.openai.com/v1",
            model="gpt-4.1-mini",
        ),
        "zai": ProviderProfile(
            api_key_env="ZAI_API_KEY",
            base_url="https://api.z.ai/api/paas/v4",
            model="GLM-4.7",
        ),
        "groq": ProviderProfile(
            api_key_env="GROQ_API_KEY",
            base_url="https://api.groq.com/openai/v1",
            model="moonshotai/kimi-k2-instruct-0905",
        ),
        "openrouter": ProviderProfile(
            api_key_env="OPENROUTER_API_KEY",
            base_url="https://openrouter.ai/api/v1",
            model="moonshotai/kimi-k2",
        ),
        "xai": ProviderProfile(
            api_key_env="XAI_API_KEY",
            base_url="https://api.x.ai/v1",
            model="grok-3-mini",
        ),
    }


class ProvidersConfig(BaseModel):
    active: str = "fireworks"
    profiles: dict[str, ProviderProfile] = Field(default_factory=default_provider_profiles)

    def profile_for(self, provider_name: str | None = None) -> ProviderProfile:
        selected = provider_name or self.active
        if selected not in self.profiles:
            raise KeyError(f"Unknown provider '{selected}'")
        return self.profiles[selected]


class ParsingConfig(BaseModel):
    primary_parser: str = "docling"
    fallback_parser: str = "pymupdf"
    default_language: str = "es"
    enable_ocr: bool = True
    ocr_text_min_chars: int = 80
    render_page_images: bool = True
    page_image_dpi: int = 144
    multimodal_max_pages_per_chunk: int = 2


class ChunkingConfig(BaseModel):
    strategy: str = "semantic"
    target_tokens: int = 8192
    overlap: int = 200


class GenerationConfig(BaseModel):
    resource_profile: str = "low"
    generation_workers: int | None = 2
    judge_workers: int | None = 1
    prompt_version: str = "v1"
    backend: str = "sync_pool"
    retries: int = 3
    max_generation_attempts_per_target: int = 3
    targets_per_chunk: int = 3
    page_batch_size: int = 100
    batch_pause_seconds: float = 2.0
    mix: dict[str, float] = Field(
        default_factory=lambda: {
            "extractive": 0.35,
            "inferential": 0.25,
            "unanswerable": 0.20,
            "multi_chunk": 0.15,
            "format_specific": 0.05,
        }
    )
    refusal_text: str = "La informacion necesaria para responder esta pregunta no se encuentra en el documento provisto."

    def resolved_worker_settings(self) -> tuple[int, int]:
        defaults = {
            "low": (2, 1),
            "balanced": (4, 2),
            "throughput": (6, 3),
        }
        generation_default, judge_default = defaults.get(self.resource_profile, defaults["low"])
        return (
            max(1, self.generation_workers or generation_default),
            max(1, self.judge_workers or judge_default),
        )


_FILTER_PRESETS: dict[str, tuple[float, float]] = {
    "strict": (0.85, 0.85),
    "balanced": (0.70, 0.70),
    "permissive": (0.55, 0.55),
}


class FiltersConfig(BaseModel):
    """Umbrales de aceptación del judge.

    Si ``preset`` se define, ``groundedness_threshold`` / ``overall_threshold``
    lo pisan cuando no sean ``None``. Esto permite elegir un preset en la UI y
    opcionalmente ajustar un único valor sin romper el otro.
    """

    preset: str = "balanced"
    groundedness_threshold: float = 0.7
    overall_threshold: float = 0.7

    @property
    def effective_groundedness(self) -> float:
        preset_values = _FILTER_PRESETS.get(self.preset, _FILTER_PRESETS["balanced"])
        return self.groundedness_threshold if self.groundedness_threshold is not None else preset_values[0]

    @property
    def effective_overall(self) -> float:
        preset_values = _FILTER_PRESETS.get(self.preset, _FILTER_PRESETS["balanced"])
        return self.overall_threshold if self.overall_threshold is not None else preset_values[1]


class ReviewConfig(BaseModel):
    sample_size: int = 100


class ExportConfig(BaseModel):
    require_eval_split: bool = True


class ProjectConfig(BaseModel):
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    parsing: ParsingConfig = Field(default_factory=ParsingConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)

    @property
    def fireworks(self) -> ProviderProfile:
        return self.providers.profile_for("fireworks")


def default_config() -> ProjectConfig:
    return ProjectConfig()


def _merge_provider_profiles(payload: dict[str, Any]) -> dict[str, Any]:
    defaults = default_provider_profiles()
    configured_profiles = payload.get("profiles", {})
    merged: dict[str, Any] = {}
    for name, default_profile in defaults.items():
        merged[name] = {
            **default_profile.model_dump(mode="json"),
            **configured_profiles.get(name, {}),
        }
    for name, profile_payload in configured_profiles.items():
        if name not in merged:
            merged[name] = profile_payload
    return merged


def _migrate_legacy_payload(raw_payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = deepcopy(raw_payload or {})
    legacy_fireworks = payload.pop("fireworks", None)
    providers_payload = payload.get("providers", {})
    if legacy_fireworks and "profiles" not in providers_payload:
        payload["providers"] = {
            "active": "fireworks",
            "profiles": {
                "fireworks": legacy_fireworks,
            },
        }
    elif "providers" not in payload:
        payload["providers"] = {}

    provider_block = payload["providers"]
    if "active" not in provider_block:
        provider_block["active"] = "fireworks"
    provider_block["profiles"] = _merge_provider_profiles(provider_block)
    return payload


def load_config(path: Path) -> ProjectConfig:
    raw_payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    payload = _migrate_legacy_payload(raw_payload)
    return ProjectConfig.model_validate(payload)


def save_config(config: ProjectConfig, path: Path) -> None:
    path.write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
