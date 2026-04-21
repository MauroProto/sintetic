from __future__ import annotations

import os
from typing import Protocol


SECRET_SERVICE_NAME = "synthetic-ds"


class SecretStore(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...

    def set_password(self, service: str, username: str, password: str) -> None: ...

    def delete_password(self, service: str, username: str) -> None: ...


class InMemorySecretStore:
    def __init__(self) -> None:
        self._values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self._values.pop((service, username), None)


class KeyringSecretStore:
    def __init__(self) -> None:
        import keyring

        self._keyring = keyring

    def get_password(self, service: str, username: str) -> str | None:
        return self._keyring.get_password(service, username)

    def set_password(self, service: str, username: str, password: str) -> None:
        self._keyring.set_password(service, username, password)

    def delete_password(self, service: str, username: str) -> None:
        try:
            self._keyring.delete_password(service, username)
        except Exception:
            return


def get_default_secret_store() -> SecretStore:
    return KeyringSecretStore()


def store_api_key(provider_name: str, api_key: str, *, store: SecretStore) -> None:
    store.set_password(SECRET_SERVICE_NAME, provider_name, api_key)


def resolve_api_key(provider_name: str, api_key_env: str, *, store: SecretStore) -> str | None:
    env_value = os.environ.get(api_key_env)
    if env_value:
        return env_value
    return store.get_password(SECRET_SERVICE_NAME, provider_name)
