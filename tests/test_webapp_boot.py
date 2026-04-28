from pathlib import Path

from fastapi.testclient import TestClient

from synthetic_ds.webapp import create_app


def test_create_app_serves_spa(tmp_path: Path) -> None:
    client = TestClient(create_app(project_dir=tmp_path))

    response = client.get("/")

    assert response.status_code in {200, 503}
    # When the frontend has been built, the SPA HTML is served. Otherwise,
    # the fallback message instructs the developer to run `pnpm build`.
    if response.status_code == 200:
        assert "<div id=\"root\">" in response.text
        assert "synthetic-ds" in response.text.lower()
    else:
        assert "pnpm" in response.text.lower()


def test_create_app_uses_external_state_dir_by_default(tmp_path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    monkeypatch.setattr("synthetic_ds.webapp.default_app_state_dir", lambda: state_dir)

    client = TestClient(create_app(project_dir=tmp_path / "project"))
    response = client.get("/api/providers")

    assert response.status_code == 200
    assert state_dir.exists()
    assert not (tmp_path / "project" / ".synthetic-ds").exists()
