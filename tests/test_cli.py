from pathlib import Path
import json

import fitz
from typer.testing import CliRunner

from synthetic_ds.cli import app
from synthetic_ds.app_state import JobStore
from synthetic_ds.secrets import InMemorySecretStore, store_api_key


class FakeBackend:
    def generate_structured(self, *, system_prompt: str, user_prompt: str, json_schema: dict, session_id: str) -> dict:
        if "overall" in json_schema.get("properties", {}):
            return {
                "relevance": 0.95,
                "groundedness": 0.92,
                "format": 1.0,
                "difficulty": 0.4,
                "overall": 0.93,
                "rationale": "ok",
            }
        return {
            "question": "Cual es el dato principal?",
            "answer": "El documento describe una prueba controlada.",
            "evidence": ["El documento describe una prueba controlada."],
            "reasoning": None,
            "supporting_facts": [],
            "question_type": "extractive",
            "difficulty": "low",
            "is_answerable": True,
        }


class FakeJobRunner:
    def __init__(self, store: JobStore) -> None:
        self.store = store

    def create_job(
        self,
        *,
        source_dir: str,
        project_dir: str,
        generate_eval: bool,
        parser_mode: str,
        resource_profile: str = "low",
        generation_workers: int | None = None,
        judge_workers: int | None = None,
        page_batch_size: int = 100,
        batch_pause_seconds: float = 2.0,
        targets_per_chunk: int = 3,
        included_files: list[str] | None = None,
        quality_preset: str | None = None,
        min_groundedness_score: float | None = None,
        min_overall_score: float | None = None,
        max_pdfs: int | None = None,
        max_pages_per_chunk: int | None = None,
        allow_partial_export: bool = False,
        agent_mode: bool = False,
    ) -> str:
        _ = (
            project_dir,
            generate_eval,
            parser_mode,
            resource_profile,
            generation_workers,
            judge_workers,
            page_batch_size,
            batch_pause_seconds,
            targets_per_chunk,
            included_files,
            allow_partial_export,
            agent_mode,
        )
        return self.store.create_job(
            source_dir=source_dir,
            provider="fireworks",
            model="accounts/fireworks/routers/kimi-k2p5-turbo",
            config={
                "dataset_mode": "multi_document",
                "dataset_mode_note": "2 PDFs detectados. Eval limpio habilitado por doc_id.",
                "parser_mode": "auto",
                "quality_preset": quality_preset or "balanced",
                "min_groundedness_score": min_groundedness_score,
                "min_overall_score": min_overall_score,
                "max_pdfs": max_pdfs,
                "max_pages_per_chunk": max_pages_per_chunk,
                "allow_partial_export": allow_partial_export,
                "agent_mode": agent_mode,
            },
            artifacts_dir=str(Path(source_dir) / "extraccion_dataset"),
        )

    def start_job(
        self,
        *,
        source_dir: str,
        project_dir: str,
        generate_eval: bool,
        parser_mode: str,
        resource_profile: str = "low",
        generation_workers: int | None = None,
        judge_workers: int | None = None,
        page_batch_size: int = 100,
        batch_pause_seconds: float = 2.0,
        targets_per_chunk: int = 3,
        included_files: list[str] | None = None,
        quality_preset: str | None = None,
        min_groundedness_score: float | None = None,
        min_overall_score: float | None = None,
        max_pdfs: int | None = None,
        max_pages_per_chunk: int | None = None,
        allow_partial_export: bool = False,
        agent_mode: bool = False,
    ) -> str:
        return self.create_job(
            source_dir=source_dir,
            project_dir=project_dir,
            generate_eval=generate_eval,
            parser_mode=parser_mode,
            resource_profile=resource_profile,
            generation_workers=generation_workers,
            judge_workers=judge_workers,
            page_batch_size=page_batch_size,
            batch_pause_seconds=batch_pause_seconds,
            targets_per_chunk=targets_per_chunk,
            included_files=included_files,
            quality_preset=quality_preset,
            min_groundedness_score=min_groundedness_score,
            min_overall_score=min_overall_score,
            max_pdfs=max_pdfs,
            max_pages_per_chunk=max_pages_per_chunk,
            allow_partial_export=allow_partial_export,
            agent_mode=agent_mode,
        )


def test_init_command_creates_config_and_workspace(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["init", "--project-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert (tmp_path / "synthetic-ds.yaml").exists()
    assert not (tmp_path / "artifacts").exists()


def test_control_and_verify_commands_exist() -> None:
    runner = CliRunner()

    for command in ("status", "pause", "resume", "cancel", "verify", "doctor", "submit", "wait", "events", "jobs"):
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0


def test_doctor_command_reports_agent_environment_as_json(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["doctor", "--project-dir", str(tmp_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] in {True, False}
    assert "dependencies" in payload
    assert "docling" in payload["dependencies"]
    assert "tesseract" in payload["dependencies"]
    assert payload["config"]["primary_parser"] in {"docling", "pymupdf"}
    assert isinstance(payload["warnings"], list)


def test_run_command_exposes_parser_mode_for_agent_environments() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["run", "--help"])

    assert result.exit_code == 0
    assert "--parser-mode" in result.output


def test_run_command_accepts_single_pdf_corpus_and_switches_to_single_document_mode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    pdf_path = pdf_dir / "single.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Resumen de prueba")
    doc.save(pdf_path)
    doc.close()

    runner = CliRunner()
    init_result = runner.invoke(app, ["init", "--project-dir", str(tmp_path)])
    assert init_result.exit_code == 0
    secret_store = InMemorySecretStore()
    store_api_key("fireworks", "fw-test-secret", store=secret_store)
    monkeypatch.setattr("synthetic_ds.cli.get_secret_store", lambda: secret_store)
    monkeypatch.setattr("synthetic_ds.cli.build_backend", lambda *args, **kwargs: FakeBackend())

    result = runner.invoke(app, ["run", str(pdf_dir), "--project-dir", str(tmp_path), "--generate-eval", "true"])

    assert result.exit_code == 0
    assert "Single-document" in result.output
    assert "mode=single_document" in result.output


def test_submit_status_events_and_wait_commands_support_json(tmp_path: Path, monkeypatch) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    for index in (1, 2):
        pdf_path = pdf_dir / f"sample-{index}.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), f"Resumen {index}")
        doc.save(pdf_path)
        doc.close()

    runner = CliRunner()
    store = JobStore(tmp_path / "app.db")
    launched: list[tuple[Path, str]] = []
    monkeypatch.setattr("synthetic_ds.cli.get_job_store", lambda: store)
    monkeypatch.setattr("synthetic_ds.cli._get_cli_job_runner", lambda _project_dir: FakeJobRunner(store), raising=False)
    monkeypatch.setattr(
        "synthetic_ds.cli._spawn_detached_job_worker",
        lambda *, project_dir, job_id: launched.append((project_dir, job_id)),
    )

    init_result = runner.invoke(app, ["init", "--project-dir", str(tmp_path)])
    assert init_result.exit_code == 0

    submit_result = runner.invoke(
        app,
        ["submit", str(pdf_dir), "--project-dir", str(tmp_path), "--json"],
    )

    assert submit_result.exit_code == 0
    submit_payload = json.loads(submit_result.output)
    job_id = submit_payload["job_id"]
    assert submit_payload["status"] == "queued"
    assert submit_payload["dataset_mode"] == "multi_document"
    assert launched == [(tmp_path, job_id)]

    status_result = runner.invoke(app, ["status", "--job-id", job_id, "--json"])
    assert status_result.exit_code == 0
    status_payload = json.loads(status_result.output)
    assert status_payload["job_id"] == job_id
    assert status_payload["status"] == "queued"

    events_result = runner.invoke(app, ["events", "--job-id", job_id, "--json"])
    assert events_result.exit_code == 0
    events_payload = json.loads(events_result.output)
    assert events_payload["job_id"] == job_id
    assert len(events_payload["events"]) >= 1
    assert events_payload["events"][0]["status"] == "queued"

    store.update_progress(
        job_id,
        stage="done",
        status="completed",
        percent=1.0,
        message="Completed successfully.",
    )
    wait_result = runner.invoke(app, ["wait", "--job-id", job_id, "--json", "--timeout-seconds", "1"])
    assert wait_result.exit_code == 0
    wait_payload = json.loads(wait_result.output)
    assert wait_payload["job_id"] == job_id
    assert wait_payload["status"] == "completed"

    jobs_result = runner.invoke(app, ["jobs", "--json"])
    assert jobs_result.exit_code == 0
    jobs_payload = json.loads(jobs_result.output)
    assert jobs_payload["jobs"][0]["job_id"] == job_id


def test_submit_uses_env_key_without_key_store_for_headless_agents(tmp_path: Path, monkeypatch) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    for index in (1, 2):
        pdf_path = pdf_dir / f"sample-{index}.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), f"Resumen {index}")
        doc.save(pdf_path)
        doc.close()

    def fail_key_store():
        raise RuntimeError("no key store")

    runner = CliRunner()
    store = JobStore(tmp_path / "app.db")
    launched: list[tuple[Path, str]] = []
    monkeypatch.setenv("FIREWORKS_API_KEY", "fw-env-secret")
    monkeypatch.setattr("synthetic_ds.cli.get_job_store", lambda: store)
    monkeypatch.setattr("synthetic_ds.cli.get_secret_store", fail_key_store)
    monkeypatch.setattr(
        "synthetic_ds.cli._spawn_detached_job_worker",
        lambda *, project_dir, job_id: launched.append((project_dir, job_id)),
    )

    result = runner.invoke(app, ["submit", str(pdf_dir), "--project-dir", str(tmp_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "queued"
    assert launched == [(tmp_path, payload["job_id"])]


def test_submit_command_accepts_quality_thresholds_for_agents(tmp_path: Path, monkeypatch) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    for index in (1, 2):
        pdf_path = pdf_dir / f"quality-{index}.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), f"Calidad {index}")
        doc.save(pdf_path)
        doc.close()

    runner = CliRunner()
    store = JobStore(tmp_path / "app.db")
    monkeypatch.setattr("synthetic_ds.cli.get_job_store", lambda: store)
    monkeypatch.setattr("synthetic_ds.cli._get_cli_job_runner", lambda _project_dir: FakeJobRunner(store), raising=False)
    monkeypatch.setattr("synthetic_ds.cli._spawn_detached_job_worker", lambda *, project_dir, job_id: None)

    result = runner.invoke(
        app,
        [
            "submit",
            str(pdf_dir),
            "--project-dir",
            str(tmp_path),
            "--quality-preset",
            "strict",
            "--min-groundedness-score",
            "0.8",
            "--min-overall-score",
            "0.8",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["config"]["quality_preset"] == "strict"
    assert payload["config"]["min_groundedness_score"] == 0.8
    assert payload["config"]["min_overall_score"] == 0.8


def test_submit_command_accepts_pdf_and_chunk_size_limits_for_agents(tmp_path: Path, monkeypatch) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    for index in (1, 2, 3):
        pdf_path = pdf_dir / f"book-{index}.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), f"Libro {index}")
        doc.save(pdf_path)
        doc.close()

    runner = CliRunner()
    store = JobStore(tmp_path / "app.db")
    monkeypatch.setattr("synthetic_ds.cli.get_job_store", lambda: store)
    monkeypatch.setattr("synthetic_ds.cli._get_cli_job_runner", lambda _project_dir: FakeJobRunner(store), raising=False)
    monkeypatch.setattr("synthetic_ds.cli._spawn_detached_job_worker", lambda *, project_dir, job_id: None)

    result = runner.invoke(
        app,
        [
            "submit",
            str(pdf_dir),
            "--project-dir",
            str(tmp_path),
            "--max-pdfs",
            "2",
            "--max-pages-per-chunk",
            "10",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["config"]["max_pdfs"] == 2
    assert payload["config"]["max_pages_per_chunk"] == 10


def test_control_commands_write_control_action_for_detached_workers(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    store = JobStore(tmp_path / "app.db")
    monkeypatch.setattr("synthetic_ds.cli.get_job_store", lambda: store)
    job_id = store.create_job(
        job_id="job-123",
        source_dir=str(tmp_path / "pdfs"),
        provider="fireworks",
        model="accounts/fireworks/routers/kimi-k2p5-turbo",
        config={},
        artifacts_dir=str(tmp_path / "pdfs" / "extraccion_dataset"),
    )

    pause_result = runner.invoke(app, ["pause", "--job-id", job_id, "--json"])
    assert pause_result.exit_code == 0
    assert json.loads(pause_result.output) == {"job_id": job_id, "action": "pause"}
    assert store.get_control_action(job_id) == "pause"

    resume_result = runner.invoke(app, ["resume", "--job-id", job_id, "--json"])
    assert resume_result.exit_code == 0
    assert json.loads(resume_result.output) == {"job_id": job_id, "action": "resume"}
    assert store.get_control_action(job_id) == "resume"

    cancel_result = runner.invoke(app, ["cancel", "--job-id", job_id, "--json"])
    assert cancel_result.exit_code == 0
    assert json.loads(cancel_result.output) == {"job_id": job_id, "action": "cancel"}
    assert store.get_control_action(job_id) == "cancel"
