from pathlib import Path
import json

import fitz
from typer.testing import CliRunner

from synthetic_ds.cli import app
from synthetic_ds.secrets import InMemorySecretStore, store_api_key


class FakeBackend:
    def generate_structured(self, *, system_prompt: str, user_prompt: str, json_schema: dict, session_id: str) -> dict:
        if "overall" in json_schema["properties"]:
            return {
                "relevance": 0.9,
                "groundedness": 0.9,
                "format": 1.0,
                "difficulty": 0.3,
                "overall": 0.92,
                "rationale": "ok",
            }
        return {
            "question": "¿Cuál es el dato principal?",
            "answer": "La tasa de retencion fue del 87.3 por ciento.",
            "evidence": ["La tasa de retencion fue del 87.3 por ciento."],
            "reasoning": None,
            "supporting_facts": [],
            "question_type": "fact",
            "difficulty": "low",
            "is_answerable": True,
        }


def test_run_command_executes_full_pipeline(tmp_path: Path, monkeypatch) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    for index, text in enumerate(
        [
            "Resumen\nLa tasa de retencion fue del 87.3 por ciento.",
            "Resumen\nLa latencia p95 se redujo a 510 ms.",
        ],
        start=1,
    ):
        pdf_path = pdf_dir / f"sample-{index}.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), text)
        doc.save(pdf_path)
        doc.close()

    runner = CliRunner()
    store = InMemorySecretStore()
    store_api_key("fireworks", "fw-test-secret", store=store)
    monkeypatch.setattr("synthetic_ds.cli.get_secret_store", lambda: store)
    monkeypatch.setattr("synthetic_ds.cli.build_backend", lambda *args, **kwargs: FakeBackend())

    init_result = runner.invoke(app, ["init", "--project-dir", str(tmp_path)])
    assert init_result.exit_code == 0

    result = runner.invoke(
        app,
        ["run", str(pdf_dir), "--project-dir", str(tmp_path), "--generate-eval", "true"],
    )

    assert result.exit_code == 0
    assert (pdf_dir / "extraccion_dataset" / "train.jsonl").exists()
    assert (pdf_dir / "extraccion_dataset" / "eval.jsonl").exists()
    assert (pdf_dir / "extraccion_dataset" / "latest.md").exists()
    assert not (tmp_path / "artifacts").exists()


def test_run_command_supports_json_output_for_agents(tmp_path: Path, monkeypatch) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    for index, text in enumerate(
        [
            "Resumen\nLa tasa de retencion fue del 87.3 por ciento.",
            "Resumen\nLa latencia p95 se redujo a 510 ms.",
        ],
        start=1,
    ):
        pdf_path = pdf_dir / f"sample-{index}.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), text)
        doc.save(pdf_path)
        doc.close()

    runner = CliRunner()
    store = InMemorySecretStore()
    store_api_key("fireworks", "fw-test-secret", store=store)
    monkeypatch.setattr("synthetic_ds.cli.get_secret_store", lambda: store)
    monkeypatch.setattr("synthetic_ds.cli.build_backend", lambda *args, **kwargs: FakeBackend())

    init_result = runner.invoke(app, ["init", "--project-dir", str(tmp_path)])
    assert init_result.exit_code == 0

    result = runner.invoke(
        app,
        ["run", str(pdf_dir), "--project-dir", str(tmp_path), "--generate-eval", "true", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["mode"] == "multi_document"
    assert payload["exports"]["train"] >= 1
    assert payload["exports"]["eval"] >= 1
    assert payload["output_dir"].endswith("extraccion_dataset")


def test_run_command_writes_phase_checkpoints_and_exposes_resume_flags(tmp_path: Path, monkeypatch) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    for index, text in enumerate(
        [
            "Resumen\nLa tasa de retencion fue del 87.3 por ciento.",
            "Resumen\nLa latencia p95 se redujo a 510 ms.",
        ],
        start=1,
    ):
        pdf_path = pdf_dir / f"sample-{index}.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), text)
        doc.save(pdf_path)
        doc.close()

    runner = CliRunner()
    store = InMemorySecretStore()
    store_api_key("fireworks", "fw-test-secret", store=store)
    monkeypatch.setattr("synthetic_ds.cli.get_secret_store", lambda: store)
    monkeypatch.setattr("synthetic_ds.cli.build_backend", lambda *args, **kwargs: FakeBackend())

    result = runner.invoke(
        app,
        [
            "run",
            str(pdf_dir),
            "--project-dir",
            str(tmp_path),
            "--generate-eval",
            "true",
            "--resume",
            "--agent",
            "--json",
        ],
    )

    assert result.exit_code == 0
    checkpoint_dir = pdf_dir / "extraccion_dataset" / ".work" / "checkpoints"
    assert (checkpoint_dir / "judge_train.json").exists()
    assert (checkpoint_dir / "judge_eval.json").exists()
    payload = json.loads(result.output)
    assert "judge_eval" in payload["completed_phases"]

    help_result = runner.invoke(app, ["run", "--help"])
    assert help_result.exit_code == 0
    assert "--from-phase" in help_result.output
    assert "--only-eval" in help_result.output


def test_run_command_enforces_minimum_quality_thresholds(tmp_path: Path, monkeypatch) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    for index, text in enumerate(
        [
            "Resumen\nLa tasa de retencion fue del 87.3 por ciento.",
            "Resumen\nLa latencia p95 se redujo a 510 ms.",
        ],
        start=1,
    ):
        pdf_path = pdf_dir / f"sample-{index}.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), text)
        doc.save(pdf_path)
        doc.close()

    runner = CliRunner()
    store = InMemorySecretStore()
    store_api_key("fireworks", "fw-test-secret", store=store)
    monkeypatch.setattr("synthetic_ds.cli.get_secret_store", lambda: store)
    monkeypatch.setattr("synthetic_ds.cli.build_backend", lambda *args, **kwargs: FakeBackend())

    result = runner.invoke(
        app,
        [
            "run",
            str(pdf_dir),
            "--project-dir",
            str(tmp_path),
            "--min-groundedness-score",
            "0.95",
            "--min-overall-score",
            "0.95",
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert "No hay ejemplos de train curados" in str(result.exception)
