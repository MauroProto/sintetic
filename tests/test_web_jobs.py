from pathlib import Path

import fitz
from fastapi.testclient import TestClient

from synthetic_ds.app_state import JobStore
from synthetic_ds.secrets import InMemorySecretStore
from synthetic_ds.webapp import create_app


class FakeRunner:
    def __init__(self, store: JobStore) -> None:
        self.store = store
        self.actions: list[tuple[str, str]] = []

    def start_job(
        self,
        *,
        source_dir: str,
        project_dir: str,
        generate_eval: bool,
        parser_mode: str,
        resource_profile: str = "low",
        generation_workers: int = 2,
        judge_workers: int = 1,
        page_batch_size: int = 100,
        batch_pause_seconds: float = 2.0,
        targets_per_chunk: int = 3,
        included_files: list[str] | None = None,
        max_pdfs: int | None = None,
        max_pages_per_chunk: int | None = None,
        quality_preset: str | None = None,
        min_groundedness_score: float | None = None,
        min_overall_score: float | None = None,
    ) -> str:
        return self.store.create_job(
            source_dir=source_dir,
            provider="fireworks",
            model="accounts/fireworks/routers/kimi-k2p5-turbo",
            config={
                "generate_eval": generate_eval,
                "parser_mode": parser_mode,
                "resource_profile": resource_profile,
                "generation_workers": generation_workers,
                "judge_workers": judge_workers,
                "page_batch_size": page_batch_size,
                "batch_pause_seconds": batch_pause_seconds,
                "targets_per_chunk": targets_per_chunk,
                "max_pdfs": max_pdfs,
                "max_pages_per_chunk": max_pages_per_chunk,
                "quality_preset": quality_preset or "balanced",
                "min_groundedness_score": min_groundedness_score,
                "min_overall_score": min_overall_score,
                "included_files": included_files,
            },
            artifacts_dir=str(Path(source_dir) / "extraccion_dataset"),
        )

    def control_job(self, *, job_id: str, action: str) -> None:
        self.actions.append((job_id, action))


def test_create_job_returns_job_id(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    for index in (1, 2):
        pdf_path = pdf_dir / f"sample-{index}.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), f"Resumen {index}")
        doc.save(pdf_path)
        doc.close()

    store = JobStore(tmp_path / "app.db")
    client = TestClient(create_app(project_dir=tmp_path, job_store=store, job_runner=FakeRunner(store)))

    response = client.post(
        "/api/jobs",
        data={
            "source_dir": str(pdf_dir),
            "generate_eval": "true",
            "parser_mode": "auto",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"]
    assert payload["status"] == "queued"
    assert payload["dataset_mode"] == "multi_document"


def test_create_job_accepts_single_pdf_and_detects_single_document_mode(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    pdf_path = pdf_dir / "single.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Resumen de prueba")
    doc.save(pdf_path)
    doc.close()

    store = JobStore(tmp_path / "app.db")
    client = TestClient(create_app(project_dir=tmp_path, job_store=store, job_runner=FakeRunner(store)))

    response = client.post(
        "/api/jobs",
        data={
            "source_dir": str(pdf_dir),
            "generate_eval": "true",
            "parser_mode": "auto",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dataset_mode"] == "single_document"
    assert "train + review" in payload["note"].lower()


def test_source_mode_endpoint_reports_single_and_multi_modes(tmp_path: Path) -> None:
    single_dir = tmp_path / "single"
    single_dir.mkdir()
    single_doc = fitz.open()
    single_doc.new_page().insert_text((72, 72), "Resumen de prueba")
    single_doc.save(single_dir / "single.pdf")
    single_doc.close()

    multi_dir = tmp_path / "multi"
    multi_dir.mkdir()
    for index in (1, 2):
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), f"Resumen {index}")
        doc.save(multi_dir / f"sample-{index}.pdf")
        doc.close()

    store = JobStore(tmp_path / "app.db")
    client = TestClient(create_app(project_dir=tmp_path, job_store=store, job_runner=FakeRunner(store)))

    single_response = client.get("/api/source-mode", params={"source_dir": str(single_dir)})
    multi_response = client.get("/api/source-mode", params={"source_dir": str(multi_dir)})

    assert single_response.status_code == 200
    assert single_response.json()["dataset_mode"] == "single_document"
    assert multi_response.status_code == 200
    assert multi_response.json()["dataset_mode"] == "multi_document"


def test_pick_folder_endpoint_returns_selected_path(tmp_path: Path, monkeypatch) -> None:
    store = JobStore(tmp_path / "app.db")
    client = TestClient(create_app(project_dir=tmp_path, job_store=store, job_runner=FakeRunner(store)))
    monkeypatch.setattr("synthetic_ds.webapp.pick_directory", lambda: str(tmp_path / "pdfs"))

    response = client.post("/api/pick-folder")

    assert response.status_code == 200
    assert response.json()["path"] == str(tmp_path / "pdfs")


def test_set_provider_key_endpoint_stores_secret(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "app.db")
    secret_store = InMemorySecretStore()
    client = TestClient(
        create_app(
            project_dir=tmp_path,
            job_store=store,
            job_runner=FakeRunner(store),
            secret_store=secret_store,
        )
    )

    response = client.post(
        "/api/provider/key",
        data={
            "provider_name": "fireworks",
            "api_key": "fw-test-secret",
        },
    )

    assert response.status_code == 200
    assert response.json()["stored"] is True
    assert secret_store.get_password("synthetic-ds", "fireworks") == "fw-test-secret"


def test_artifacts_endpoint_lists_files_for_source_folders_outside_project_root(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    external_source = tmp_path / "PDFs Pepito"
    artifacts_dir = external_source / "extraccion_dataset"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "train.jsonl").write_text("{}", encoding="utf-8")

    store = JobStore(project_dir / ".synthetic-ds" / "app.db")
    job_id = store.create_job(
        source_dir=str(external_source),
        provider="fireworks",
        model="accounts/fireworks/routers/kimi-k2p5-turbo",
        config={"generate_eval": False, "parser_mode": "auto"},
        artifacts_dir=str(artifacts_dir),
    )
    client = TestClient(create_app(project_dir=project_dir, job_store=store, job_runner=FakeRunner(store)))

    response = client.get(f"/api/jobs/{job_id}/artifacts")

    assert response.status_code == 200
    payload = response.json()
    paths = [item["path"] for item in payload["items"]]
    assert "train.jsonl" in paths


def test_job_action_endpoint_calls_runner_control(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "app.db")
    runner = FakeRunner(store)
    job_id = store.create_job(
        source_dir=str(tmp_path / "pdfs"),
        provider="fireworks",
        model="accounts/fireworks/routers/kimi-k2p5-turbo",
        config={"generate_eval": False, "parser_mode": "auto"},
        artifacts_dir=str(tmp_path / "pdfs" / "extraccion_dataset"),
    )
    client = TestClient(create_app(project_dir=tmp_path, job_store=store, job_runner=runner))

    response = client.post(f"/api/jobs/{job_id}/pause")

    assert response.status_code == 200
    assert response.json()["action"] == "pause"
    assert runner.actions == [(job_id, "pause")]
