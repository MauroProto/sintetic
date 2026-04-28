from pathlib import Path

from synthetic_ds.config import FiltersConfig, default_config, load_config


def test_default_config_contains_multiple_provider_presets() -> None:
    config = default_config()

    assert config.providers.active == "fireworks"
    assert {"fireworks", "openai", "zai", "groq", "openrouter", "xai"} <= set(config.providers.profiles)
    assert config.generation.resource_profile == "low"
    assert config.generation.generation_workers == 2
    assert config.generation.judge_workers == 1
    assert config.generation.page_batch_size == 100
    assert config.generation.batch_pause_seconds == 2.0
    assert config.generation.resolved_worker_settings() == (2, 1)
    assert config.chunking.max_pages_per_chunk == 25
    assert config.parsing.docling_max_pages == 100
    assert config.parsing.docling_max_ram_mb == 3072
    assert config.export.allow_partial_export is False


def test_load_config_migrates_legacy_fireworks_section(tmp_path: Path) -> None:
    config_path = tmp_path / "synthetic-ds.yaml"
    config_path.write_text(
        """
fireworks:
  api_key_env: FIREWORKS_API_KEY
  base_url: https://api.fireworks.ai/inference/v1
  model: accounts/fireworks/routers/kimi-k2p5-turbo
  max_tokens: 111
  temperature: 0.3
  concurrency: 2
parsing:
  primary_parser: pymupdf
  fallback_parser: pymupdf
  default_language: es
chunking:
  strategy: headings_first
  target_tokens: 256
  overlap: 32
generation:
  prompt_version: v1
  backend: sync_pool
  retries: 3
  mix:
    extractive: 1.0
  refusal_text: nope
filters:
  groundedness_threshold: 0.7
  overall_threshold: 0.7
review:
  sample_size: 10
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.providers.active == "fireworks"
    assert config.providers.profiles["fireworks"].max_tokens == 111


def test_worker_resolution_allows_explicit_overrides() -> None:
    config = default_config()
    config.generation.resource_profile = "throughput"
    config.generation.generation_workers = 3
    config.generation.judge_workers = 2

    assert config.generation.resolved_worker_settings() == (3, 2)


def test_filter_preset_sets_effective_thresholds_when_not_overridden() -> None:
    filters = FiltersConfig(preset="strict")

    assert filters.effective_groundedness == 0.85
    assert filters.effective_overall == 0.85


def test_filter_thresholds_can_override_preset_individually() -> None:
    filters = FiltersConfig(
        preset="strict",
        groundedness_threshold=0.8,
        overall_threshold=None,
    )

    assert filters.effective_groundedness == 0.8
    assert filters.effective_overall == 0.85
