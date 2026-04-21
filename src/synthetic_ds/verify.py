from __future__ import annotations

import json
import tempfile
from pathlib import Path

import fitz
from typer.testing import CliRunner

from synthetic_ds.app_state import JobStore
from synthetic_ds.secrets import InMemorySecretStore, resolve_api_key, store_api_key


class VerifyFakeBackend:
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


class VerifyFakeRunner:
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
            },
            artifacts_dir=str(Path(source_dir) / "extraccion_dataset"),
        )

    def control_job(self, *, job_id: str, action: str) -> None:
        self.actions.append((job_id, action))


def _create_fixture_pdf(target: Path) -> None:
    doc = fitz.open()
    for text in [
        "Resumen\nEl documento describe una prueba controlada.",
        "Resultados\nLa tasa de retencion fue del 87.3 por ciento.",
        "Operacion\nEl sistema procesa por lotes de paginas.",
    ]:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(target)
    doc.close()


def _create_fixture_corpus(pdf_dir: Path) -> None:
    _create_fixture_pdf(pdf_dir / "sample-a.pdf")
    _create_fixture_pdf(pdf_dir / "sample-b.pdf")


def _create_single_fixture_corpus(pdf_dir: Path) -> None:
    _create_fixture_pdf(pdf_dir / "sample-a.pdf")


def run_mock_full_verification(*, base_tmp_dir: Path | None = None) -> dict[str, object]:
    temp_root_ctx = tempfile.TemporaryDirectory(dir=base_tmp_dir)
    try:
        from synthetic_ds.cli import app
        import synthetic_ds.cli as cli_module
        from synthetic_ds.webapp import create_app
        from fastapi.testclient import TestClient

        workspace = Path(temp_root_ctx.name)
        project_dir = workspace / "project"
        pdf_dir = workspace / "PDFs Pepito"
        single_pdf_dir = workspace / "PDFs Solo"
        project_dir.mkdir(parents=True, exist_ok=True)
        pdf_dir.mkdir(parents=True, exist_ok=True)
        single_pdf_dir.mkdir(parents=True, exist_ok=True)
        _create_fixture_corpus(pdf_dir)
        _create_single_fixture_corpus(single_pdf_dir)

        store = InMemorySecretStore()
        store_api_key("fireworks", "fw-test-secret", store=store)

        original_get_secret_store = cli_module.get_secret_store
        original_build_backend = cli_module.build_backend
        cli_module.get_secret_store = lambda: store
        cli_module.build_backend = lambda *args, **kwargs: VerifyFakeBackend()
        try:
            runner = CliRunner()
            assert runner.invoke(app, ["init", "--project-dir", str(project_dir)]).exit_code == 0
            assert runner.invoke(app, ["ingest", str(pdf_dir), "--project-dir", str(project_dir)]).exit_code == 0
            assert runner.invoke(app, ["split", "--project-dir", str(project_dir)]).exit_code == 0
            assert runner.invoke(app, ["generate", "--split", "train", "--project-dir", str(project_dir)]).exit_code == 0
            assert runner.invoke(app, ["curate", "--split", "train", "--project-dir", str(project_dir)]).exit_code == 0
            assert runner.invoke(app, ["generate", "--split", "eval", "--project-dir", str(project_dir)]).exit_code == 0
            assert runner.invoke(app, ["curate", "--split", "eval", "--project-dir", str(project_dir)]).exit_code == 0
            assert runner.invoke(app, ["export", "--project-dir", str(project_dir)]).exit_code == 0
            assert runner.invoke(app, ["report", "--project-dir", str(project_dir)]).exit_code == 0

            run_pdf_dir = workspace / "PDFs Pepito Run"
            single_run_pdf_dir = workspace / "PDF Solo Run"
            run_pdf_dir.mkdir(parents=True, exist_ok=True)
            single_run_pdf_dir.mkdir(parents=True, exist_ok=True)
            _create_fixture_corpus(run_pdf_dir)
            _create_single_fixture_corpus(single_run_pdf_dir)
            run_result = runner.invoke(
                app,
                [
                    "run",
                    str(run_pdf_dir),
                    "--project-dir",
                    str(project_dir),
                    "--generate-eval",
                    "true",
                    "--resource-profile",
                    "low",
                    "--generation-workers",
                    "2",
                    "--judge-workers",
                    "1",
                    "--page-batch-size",
                    "50",
                    "--batch-pause-seconds",
                    "0",
                ],
            )
            assert run_result.exit_code == 0
            output_dir = run_pdf_dir / "extraccion_dataset"
            visible_files = sorted(path.name for path in output_dir.iterdir())
            assert visible_files == [
                ".work",
                "eval.jsonl",
                "latest.md",
                "review_sample.csv",
                "review_sample.jsonl",
                "train.jsonl",
            ]

            single_run_result = runner.invoke(
                app,
                [
                    "run",
                    str(single_run_pdf_dir),
                    "--project-dir",
                    str(project_dir),
                    "--generate-eval",
                    "true",
                    "--resource-profile",
                    "low",
                    "--generation-workers",
                    "2",
                    "--judge-workers",
                    "1",
                    "--page-batch-size",
                    "50",
                    "--batch-pause-seconds",
                    "0",
                ],
            )
            assert single_run_result.exit_code == 0
            single_output_dir = single_run_pdf_dir / "extraccion_dataset"
            single_visible_files = sorted(path.name for path in single_output_dir.iterdir())
            assert single_visible_files == [
                ".work",
                "latest.md",
                "review_sample.csv",
                "review_sample.jsonl",
                "train.jsonl",
            ]
            assert "Single-document" in (single_output_dir / "latest.md").read_text(encoding="utf-8")

            job_store = JobStore(workspace / "app.db")
            fake_runner = VerifyFakeRunner(job_store)
            client = TestClient(
                create_app(project_dir=project_dir, job_store=job_store, job_runner=fake_runner, secret_store=store)
            )
            response = client.get("/")
            assert response.status_code in {200, 503}
            if response.status_code == 200:
                assert "<div id=\"root\">" in response.text
            mode_response = client.get("/api/source-mode", params={"source_dir": str(single_pdf_dir)})
            assert mode_response.status_code == 200
            assert mode_response.json()["dataset_mode"] == "single_document"
            api_response = client.post(
                "/api/jobs",
                data={
                    "source_dir": str(pdf_dir),
                    "generate_eval": "true",
                    "parser_mode": "auto",
                    "resource_profile": "low",
                    "generation_workers": "2",
                    "judge_workers": "1",
                    "page_batch_size": "50",
                    "batch_pause_seconds": "0",
                },
            )
            assert api_response.status_code == 200
            job_id = api_response.json()["job_id"]
            single_job_response = client.post(
                "/api/jobs",
                data={
                    "source_dir": str(single_pdf_dir),
                    "generate_eval": "true",
                    "parser_mode": "auto",
                    "resource_profile": "low",
                    "generation_workers": "2",
                    "judge_workers": "1",
                    "page_batch_size": "50",
                    "batch_pause_seconds": "0",
                },
            )
            assert single_job_response.status_code == 200
            assert single_job_response.json()["dataset_mode"] == "single_document"
            for action in ("pause", "resume", "cancel"):
                action_response = client.post(f"/api/jobs/{job_id}/{action}")
                assert action_response.status_code == 200
            assert fake_runner.actions == [(job_id, "pause"), (job_id, "resume"), (job_id, "cancel")]
        finally:
            cli_module.get_secret_store = original_get_secret_store
            cli_module.build_backend = original_build_backend

        return {"ok": True, "mode": "mock-full"}
    finally:
        temp_root_ctx.cleanup()


def run_real_smoke_verification(*, project_dir: Path, secret_store) -> dict[str, object]:
    from synthetic_ds.cli import build_backend
    from synthetic_ds.config import default_config
    from synthetic_ds.cli import app
    import synthetic_ds.cli as cli_module

    config = default_config()
    profile = config.providers.profile_for("fireworks")
    api_key = resolve_api_key("fireworks", profile.api_key_env, store=secret_store)
    if not api_key:
        raise RuntimeError("Missing Fireworks API key for real-smoke verification")

    temp_root_ctx = tempfile.TemporaryDirectory()
    try:
        workspace = Path(temp_root_ctx.name)
        project_root = workspace / "project"
        pdf_dir = workspace / "PDFs Pepito"
        single_pdf_dir = workspace / "PDFs Solo"
        project_root.mkdir(parents=True, exist_ok=True)
        pdf_dir.mkdir(parents=True, exist_ok=True)
        single_pdf_dir.mkdir(parents=True, exist_ok=True)
        _create_fixture_corpus(pdf_dir)
        _create_single_fixture_corpus(single_pdf_dir)

        original_get_secret_store = cli_module.get_secret_store
        cli_module.get_secret_store = lambda: secret_store
        try:
            runner = CliRunner()
            assert runner.invoke(app, ["init", "--project-dir", str(project_root)]).exit_code == 0
            single_result = runner.invoke(
                app,
                [
                    "run",
                    str(single_pdf_dir),
                    "--project-dir",
                    str(project_root),
                    "--generate-eval",
                    "true",
                    "--resource-profile",
                    "low",
                    "--generation-workers",
                    "2",
                    "--judge-workers",
                    "1",
                    "--page-batch-size",
                    "20",
                    "--batch-pause-seconds",
                    "0",
                ],
            )
            if single_result.exit_code != 0:
                raise RuntimeError(single_result.stdout or single_result.stderr or "single-document real-smoke run failed")
            single_output_dir = single_pdf_dir / "extraccion_dataset"
            single_train_path = single_output_dir / "train.jsonl"
            single_report_path = single_output_dir / "latest.md"
            if not single_train_path.exists() or not single_report_path.exists():
                raise RuntimeError("single-document real-smoke did not produce expected output files")
            if (single_output_dir / "eval.jsonl").exists():
                raise RuntimeError("single-document real-smoke should not export eval.jsonl")
            if "Single-document" not in single_report_path.read_text(encoding="utf-8"):
                raise RuntimeError("single-document real-smoke did not annotate the dataset mode")

            result = runner.invoke(
                app,
                [
                    "run",
                    str(pdf_dir),
                    "--project-dir",
                    str(project_root),
                    "--generate-eval",
                    "true",
                    "--resource-profile",
                    "low",
                    "--generation-workers",
                    "2",
                    "--judge-workers",
                    "1",
                    "--page-batch-size",
                    "20",
                    "--batch-pause-seconds",
                    "0",
                ],
            )
            if result.exit_code != 0:
                raise RuntimeError(result.stdout or result.stderr or "real-smoke run failed")
            output_dir = pdf_dir / "extraccion_dataset"
            train_path = output_dir / "train.jsonl"
            report_path = output_dir / "latest.md"
            if not train_path.exists() or not report_path.exists():
                raise RuntimeError("real-smoke did not produce expected output files")
            records = [
                json.loads(line)
                for line in train_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if not records:
                raise RuntimeError("real-smoke produced an empty train.jsonl")
            first = records[0]
            if not first.get("messages") or not first["messages"][-1].get("content", "").strip():
                raise RuntimeError("real-smoke produced malformed training records")
            return {"ok": True, "mode": "real-smoke", "train_records": len(records)}
        finally:
            cli_module.get_secret_store = original_get_secret_store
    finally:
        temp_root_ctx.cleanup()
