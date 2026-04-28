import os

from synthetic_ds.secrets import InMemorySecretStore, resolve_api_key, store_api_key


def test_store_api_key_uses_secret_store_without_exposing_yaml() -> None:
    store = InMemorySecretStore()

    store_api_key("fireworks", "fw-secret", store=store)

    assert store.get_password("synthetic-ds", "fireworks") == "fw-secret"


def test_resolve_api_key_prefers_environment_variable(monkeypatch) -> None:
    store = InMemorySecretStore()
    store_api_key("fireworks", "fw-secret", store=store)
    monkeypatch.setenv("FIREWORKS_API_KEY", "fw-from-env")

    result = resolve_api_key("fireworks", "FIREWORKS_API_KEY", store=store)

    assert result == "fw-from-env"
