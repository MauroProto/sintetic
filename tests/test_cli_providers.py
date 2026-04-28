from pathlib import Path

from typer.testing import CliRunner

from synthetic_ds.cli import app, build_backend
from synthetic_ds.config import default_config
from synthetic_ds.secrets import InMemorySecretStore


def test_provider_set_key_stores_secret_and_not_in_config(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    store = InMemorySecretStore()
    monkeypatch.setattr("synthetic_ds.cli.get_secret_store", lambda: store)

    init_result = runner.invoke(app, ["init", "--project-dir", str(tmp_path)])
    assert init_result.exit_code == 0

    result = runner.invoke(
        app,
        ["provider", "set-key", "fireworks", "--project-dir", str(tmp_path), "--api-key", "fw-test-secret"],
    )

    assert result.exit_code == 0
    assert store.get_password("synthetic-ds", "fireworks") == "fw-test-secret"
    assert "fw-test-secret" not in (tmp_path / "synthetic-ds.yaml").read_text(encoding="utf-8")


def test_provider_use_switches_active_provider(tmp_path: Path) -> None:
    runner = CliRunner()
    init_result = runner.invoke(app, ["init", "--project-dir", str(tmp_path)])
    assert init_result.exit_code == 0

    result = runner.invoke(app, ["provider", "use", "zai", "--project-dir", str(tmp_path)])

    assert result.exit_code == 0
    text = (tmp_path / "synthetic-ds.yaml").read_text(encoding="utf-8")
    assert "active: zai" in text


def test_provider_set_key_reads_from_stdin_for_agents(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    store = InMemorySecretStore()
    monkeypatch.setattr("synthetic_ds.cli.get_secret_store", lambda: store)

    init_result = runner.invoke(app, ["init", "--project-dir", str(tmp_path)])
    assert init_result.exit_code == 0

    result = runner.invoke(
        app,
        ["provider", "set-key", "fireworks", "--project-dir", str(tmp_path), "--stdin"],
        input="fw-stdin-secret\n",
    )

    assert result.exit_code == 0
    assert store.get_password("synthetic-ds", "fireworks") == "fw-stdin-secret"


def test_build_backend_uses_env_key_without_key_store(monkeypatch) -> None:
    monkeypatch.setenv("FIREWORKS_API_KEY", "fw-env-secret")

    def fail_key_store():
        raise RuntimeError("no key store")

    monkeypatch.setattr("synthetic_ds.cli.get_secret_store", fail_key_store)

    backend = build_backend(default_config())

    assert backend.api_key == "fw-env-secret"
