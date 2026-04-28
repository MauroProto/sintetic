from __future__ import annotations

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import webbrowser

import typer

from synthetic_ds.config import ProjectConfig, apply_quality_overrides, default_config, load_config, save_config
from synthetic_ds.ingest import discover_pdf_paths
from synthetic_ds.inference import OpenAICompatibleInferenceBackend
from synthetic_ds.models import (
    ChunkRecord,
    CuratedSummary,
    DocumentRecord,
    GeneratedExample,
    SplitManifest,
)
from synthetic_ds.pipeline import PipelineSession
from synthetic_ds.secrets import get_default_secret_store, resolve_api_key, store_api_key
from synthetic_ds.splitter import dataset_mode_label, dataset_mode_summary, detect_dataset_mode
from synthetic_ds.storage import (
    PHASES,
    build_project_paths,
    build_run_output_dir,
    ensure_project_layout,
    read_json,
    read_jsonl,
    write_json,
    write_jsonl,
)
from synthetic_ds.verify import run_mock_full_verification, run_real_smoke_verification
from synthetic_ds.app_state import JobStore, default_app_state_dir

app = typer.Typer(no_args_is_help=True, add_completion=False)
provider_app = typer.Typer(no_args_is_help=True, add_completion=False)
app.add_typer(provider_app, name="provider")

TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}


@app.callback()
def main() -> None:
    """synthetic-ds CLI."""


def _emit_json(payload: object) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=True))


def _jsonl_line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _job_payload(job) -> dict:
    payload = job.model_dump(mode="json")
    payload["dataset_mode"] = job.config.get("dataset_mode")
    payload["note"] = job.config.get("dataset_mode_note")
    return payload


def _get_cli_job_runner(project_dir: Path):
    from synthetic_ds.job_runner import JobRunner

    return JobRunner(project_dir=project_dir, job_store=get_job_store())


def _spawn_detached_job_worker(*, project_dir: Path, job_id: str) -> None:
    command = [
        sys.executable,
        "-c",
        "from synthetic_ds.cli import app; app()",
        "internal-run-job",
        "--job-id",
        job_id,
        "--project-dir",
        str(project_dir.resolve()),
    ]
    popen_kwargs: dict[str, object] = {
        "cwd": str(project_dir.resolve()),
        "env": os.environ.copy(),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        creationflags = 0
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        popen_kwargs["creationflags"] = creationflags
    else:
        popen_kwargs["start_new_session"] = True
    subprocess.Popen(command, **popen_kwargs)


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise typer.BadParameter(f"Expected a boolean value, received '{value}'")


def _apply_cli_quality_overrides(
    config: ProjectConfig,
    *,
    quality_preset: str | None,
    min_groundedness_score: float | None,
    min_overall_score: float | None,
) -> ProjectConfig:
    try:
        return apply_quality_overrides(
            config,
            quality_preset=quality_preset,
            min_groundedness_score=min_groundedness_score,
            min_overall_score=min_overall_score,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _apply_cli_parser_mode(config: ProjectConfig, parser_mode: str) -> ProjectConfig:
    normalized = parser_mode.strip().lower()
    updated = config.model_copy(deep=True)
    if normalized == "auto":
        return updated
    if normalized == "fast":
        updated.parsing.primary_parser = "pymupdf"
        updated.parsing.fallback_parser = "pymupdf"
        updated.parsing.enable_ocr = False
        updated.parsing.render_page_images = False
        return updated
    if normalized == "ocr_safe":
        updated.parsing.primary_parser = "docling"
        updated.parsing.fallback_parser = "pymupdf"
        updated.parsing.enable_ocr = True
        updated.parsing.render_page_images = True
        return updated
    raise typer.BadParameter("Unknown parser mode. Use auto, fast, or ocr_safe.")


def _is_agent_mode(force_agent: bool) -> bool:
    if force_agent or os.environ.get("SYNTHETIC_DS_AGENT_MODE") == "1":
        return True
    try:
        return not sys.stdin.isatty()
    except Exception:
        return False


def _apply_agent_defaults(
    config: ProjectConfig,
    *,
    generation_workers: int,
    judge_workers: int,
    batch_pause_seconds: float,
) -> tuple[int, int, float]:
    config.generation.backend = "sync_pool"
    provider = config.providers.profile_for()
    provider.concurrency = min(provider.concurrency, 2)
    return (
        min(generation_workers, 1),
        min(judge_workers, 1),
        max(batch_pause_seconds, 5.0),
    )


def _normalize_from_phase(from_phase: str | None, *, only_train: bool, only_eval: bool) -> str | None:
    if from_phase == "generate":
        return "generate_eval" if only_eval else "generate_train"
    if from_phase == "judge":
        return "judge_eval" if only_eval else "judge_train"
    return from_phase


def _validate_phase_flags(from_phase: str | None, only_train: bool, only_eval: bool) -> str | None:
    from_phase = _normalize_from_phase(from_phase, only_train=only_train, only_eval=only_eval)
    if from_phase is not None and from_phase not in PHASES:
        valid = ", ".join([*PHASES, "generate", "judge"])
        raise typer.BadParameter(f"Unknown phase '{from_phase}'. Valid phases: {valid}")
    if only_train and only_eval:
        raise typer.BadParameter("Use --only-train or --only-eval, not both.")
    return from_phase


def _should_run_phase(phase: str, *, completed: set[str], resume: bool, from_phase: str | None) -> bool:
    if from_phase is not None:
        return PHASES.index(phase) >= PHASES.index(from_phase)
    if resume and phase in completed:
        return False
    return True


def get_secret_store():
    try:
        return get_default_secret_store()
    except Exception as exc:  # pragma: no cover - depends on host keychain backend
        raise typer.BadParameter(
            "No secure key store is available. Export the provider env var or install a system keychain backend."
        ) from exc


def get_job_store() -> JobStore:
    state_dir = default_app_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    return JobStore(state_dir / "app.db")


def init_project(project_dir: Path) -> tuple[Path, object]:
    project_dir = project_dir.resolve()
    project_dir.mkdir(parents=True, exist_ok=True)
    paths = build_project_paths(project_dir)
    if paths.config_path.exists():
        save_config(load_config(paths.config_path), paths.config_path)
    else:
        save_config(default_config(), paths.config_path)
    return project_dir, paths


def _paths_and_config(project_dir: Path, *, run_dir: Path | None = None, work_subdir: str | None = None):
    project_dir, _project_paths = init_project(project_dir)
    paths = build_project_paths(project_dir, run_dir=run_dir, work_subdir=work_subdir)
    ensure_project_layout(paths)
    config = load_config(paths.config_path)
    return paths, config


def _module_status(module_name: str) -> dict[str, object]:
    return {"found": importlib.util.find_spec(module_name) is not None}


def _command_status(command_name: str, *, version_args: list[str] | None = None) -> dict[str, object]:
    command_path = shutil.which(command_name)
    status: dict[str, object] = {"found": command_path is not None, "path": command_path}
    if command_path and version_args:
        try:
            result = subprocess.run(
                [command_path, *version_args],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=3,
            )
            first_line = (result.stdout or "").splitlines()[0] if result.stdout else ""
            status["version"] = first_line
        except Exception as exc:  # pragma: no cover - host command behavior varies
            status["version_error"] = str(exc)
    return status


def _doctor_dependencies() -> dict[str, dict[str, object]]:
    return {
        "docling": _module_status("docling"),
        "pymupdf": _module_status("fitz"),
        "tesseract": _command_status("tesseract", version_args=["--version"]),
        "tiktoken": _module_status("tiktoken"),
        "sentence_transformers": _module_status("sentence_transformers"),
    }


def _provider_key_status(config: ProjectConfig) -> dict[str, object]:
    selected_provider = config.providers.active
    profile = config.providers.profile_for(selected_provider)
    env_present = bool(os.environ.get(profile.api_key_env))
    stored_key_present = False
    key_store_error: str | None = None
    if not env_present:
        try:
            stored_key_present = bool(resolve_api_key(selected_provider, profile.api_key_env, store=get_default_secret_store()))
        except Exception as exc:  # pragma: no cover - depends on host keychain backend
            key_store_error = str(exc)
    payload: dict[str, object] = {
        "active": selected_provider,
        "model": profile.model,
        "base_url": profile.base_url,
        "env": profile.api_key_env,
        "env_present": env_present,
        "stored_key_present": stored_key_present,
        "configured": env_present or stored_key_present,
    }
    if key_store_error:
        payload["key_store_error"] = key_store_error
    return payload


def _doctor_payload(project_dir: Path) -> dict[str, object]:
    paths, config = _paths_and_config(project_dir)
    dependencies = _doctor_dependencies()
    provider = _provider_key_status(config)
    warnings: list[str] = []

    primary_parser = config.parsing.primary_parser
    fallback_parser = config.parsing.fallback_parser
    if primary_parser == "docling" and not dependencies["docling"]["found"]:
        warnings.append(
            "docling is not installed. Install parse extras with `uv sync --extra parse` "
            "or run agents with `--parser-mode fast` to force PyMuPDF."
        )
    if primary_parser == "pymupdf" and not dependencies["pymupdf"]["found"]:
        warnings.append("PyMuPDF is not installed, so the configured primary parser cannot run.")
    if fallback_parser == "pymupdf" and not dependencies["pymupdf"]["found"]:
        warnings.append("PyMuPDF fallback is not installed; PDF parsing has no safe fallback.")
    if config.parsing.enable_ocr and not dependencies["tesseract"]["found"]:
        warnings.append(
            "OCR is enabled but tesseract is missing. Install tesseract or use `--parser-mode fast` for text PDFs."
        )
    if not provider["configured"]:
        warnings.append(
            f"Provider key is not configured. Export {provider['env']} or use "
            f"`synthetic-ds provider set-key {provider['active']} --stdin`."
        )
    if config.chunking.max_pages_per_chunk is None:
        warnings.append("chunking.max_pages_per_chunk is disabled; large sparse PDFs can create oversized chunks.")
    if config.generation.targets_per_chunk < 1:
        warnings.append("generation.targets_per_chunk must be at least 1.")

    return {
        "ok": not warnings,
        "project_dir": str(paths.project_dir),
        "dependencies": dependencies,
        "provider": provider,
        "config": {
            "primary_parser": primary_parser,
            "fallback_parser": fallback_parser,
            "ocr_enabled": config.parsing.enable_ocr,
            "docling_max_pages": config.parsing.docling_max_pages,
            "docling_max_ram_mb": config.parsing.docling_max_ram_mb,
            "chunking_strategy": config.chunking.strategy,
            "target_tokens": config.chunking.target_tokens,
            "max_pages_per_chunk": config.chunking.max_pages_per_chunk,
            "targets_per_chunk": config.generation.targets_per_chunk,
            "generation_workers": config.generation.generation_workers,
            "judge_workers": config.generation.judge_workers,
            "page_batch_size": config.generation.page_batch_size,
        },
        "warnings": warnings,
    }


def build_backend(
    config: ProjectConfig,
    *,
    provider_name: str | None = None,
    store=None,
) -> OpenAICompatibleInferenceBackend:
    selected_provider = provider_name or config.providers.active
    profile = config.providers.profile_for(selected_provider)
    api_key = os.environ.get(profile.api_key_env)
    if not api_key:
        secret_store = store or get_secret_store()
        api_key = resolve_api_key(selected_provider, profile.api_key_env, store=secret_store)
    if not api_key:
        raise typer.BadParameter(
            f"Missing API key for provider '{selected_provider}'. "
            f"Run `synthetic-ds provider set-key {selected_provider}` or export {profile.api_key_env}."
        )
    return OpenAICompatibleInferenceBackend(
        api_key=api_key,
        base_url=profile.base_url,
        model=profile.model,
        max_tokens=profile.max_tokens,
        temperature=profile.temperature,
        concurrency=profile.concurrency,
        extra_headers=profile.extra_headers,
    )


def run_ingest(
    paths,
    config: ProjectConfig,
    *,
    pdf_dir: Path,
    recursive: bool = True,
    max_documents: int | None = None,
) -> tuple[int, int]:
    session = PipelineSession(paths=paths, config=config)
    return session.ingest(pdf_dir=pdf_dir, recursive=recursive, max_documents=max_documents)


def run_split(paths) -> SplitManifest:
    session = PipelineSession(paths=paths, config=default_config())
    return session.split()


def run_generate(
    paths,
    config: ProjectConfig,
    *,
    split_name: str,
    store=None,
    doc_ids: list[str] | None = None,
    chunk_ids: list[str] | None = None,
) -> int:
    backend = build_backend(config, store=store)
    session = PipelineSession(paths=paths, config=config, backend=backend)
    return session.generate_split(split_name, doc_ids=doc_ids, chunk_ids=chunk_ids)


def run_curate(paths, config: ProjectConfig, *, split_name: str, store=None) -> CuratedSummary:
    backend = build_backend(config, store=store)
    session = PipelineSession(paths=paths, config=config, backend=backend)
    return session.curate_split(split_name)


def run_export(paths, config: ProjectConfig) -> tuple[int, int, int]:
    session = PipelineSession(paths=paths, config=config)
    return session.export()


def run_report(paths) -> tuple[Path, str]:
    session = PipelineSession(paths=paths, config=default_config())
    return session.report()


@app.command()
def init(project_dir: Path = typer.Option(Path("."), "--project-dir", file_okay=False, dir_okay=True)) -> None:
    project_dir, _paths = init_project(project_dir)
    typer.echo(f"Initialized project at {project_dir}")


@app.command()
def ingest(
    pdf_dir: Path,
    project_dir: Path = typer.Option(Path("."), "--project-dir", file_okay=False, dir_okay=True),
    recursive: str = typer.Option("true", "--recursive"),
    max_pdfs: int | None = typer.Option(None, "--max-pdfs"),
    max_pages_per_chunk: int | None = typer.Option(None, "--max-pages-per-chunk"),
) -> None:
    paths, config = _paths_and_config(project_dir)
    if max_pdfs is not None and max_pdfs < 1:
        raise typer.BadParameter("--max-pdfs must be greater than zero.")
    if max_pages_per_chunk is not None and max_pages_per_chunk < 1:
        raise typer.BadParameter("--max-pages-per-chunk must be greater than zero.")
    if max_pages_per_chunk is not None:
        config.chunking.max_pages_per_chunk = max_pages_per_chunk
    document_count, chunk_count = run_ingest(
        paths,
        config,
        pdf_dir=pdf_dir,
        recursive=parse_bool(recursive),
        max_documents=max_pdfs,
    )
    typer.echo(f"Ingested {document_count} documents and {chunk_count} chunks")


@app.command()
def split(project_dir: Path = typer.Option(Path("."), "--project-dir", file_okay=False, dir_okay=True)) -> None:
    paths, _config = _paths_and_config(project_dir)
    manifest = run_split(paths)
    typer.echo(
        f"Frozen split in mode {manifest.dataset_mode} with "
        f"{len(manifest.train_doc_ids)} train docs and {len(manifest.eval_doc_ids)} eval docs"
    )


@app.command()
def generate(
    split: str = typer.Option(..., "--split"),
    project_dir: Path = typer.Option(Path("."), "--project-dir", file_okay=False, dir_okay=True),
    resource_profile: str = typer.Option("low", "--resource-profile"),
    generation_workers: int = typer.Option(2, "--generation-workers"),
) -> None:
    paths, config = _paths_and_config(project_dir)
    config.generation.resource_profile = resource_profile
    config.generation.generation_workers = generation_workers
    total = run_generate(paths, config, split_name=split)
    typer.echo(f"Generated {total} examples for {split}")


@app.command()
def curate(
    split: str = typer.Option(..., "--split"),
    project_dir: Path = typer.Option(Path("."), "--project-dir", file_okay=False, dir_okay=True),
    resource_profile: str = typer.Option("low", "--resource-profile"),
    judge_workers: int = typer.Option(1, "--judge-workers"),
) -> None:
    paths, config = _paths_and_config(project_dir)
    config.generation.resource_profile = resource_profile
    config.generation.judge_workers = judge_workers
    summary = run_curate(paths, config, split_name=split)
    typer.echo(f"Curated {split}: accepted {summary.accepted} / {summary.total_input}")


@app.command()
def export(project_dir: Path = typer.Option(Path("."), "--project-dir", file_okay=False, dir_okay=True)) -> None:
    paths, config = _paths_and_config(project_dir)
    train_count, eval_count, review_count = run_export(paths, config)
    typer.echo(f"Exported {train_count} train, {eval_count} eval and {review_count} review items")


@app.command()
def report(project_dir: Path = typer.Option(Path("."), "--project-dir", file_okay=False, dir_okay=True)) -> None:
    paths, _config = _paths_and_config(project_dir)
    _report_path, markdown = run_report(paths)
    typer.echo(markdown)


@app.command("app")
def serve_app(
    project_dir: Path = typer.Option(Path("."), "--project-dir", file_okay=False, dir_okay=True),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8787, "--port"),
    open_browser: str = typer.Option("true", "--open-browser"),
) -> None:
    """Launch the local visual app."""
    project_dir, _paths = init_project(project_dir)
    from synthetic_ds.webapp import create_app
    import uvicorn

    if parse_bool(open_browser):
        webbrowser.open(f"http://{host}:{port}")

    uvicorn.run(create_app(project_dir=project_dir), host=host, port=port, log_level="info")


@app.command()
def submit(
    pdf_dir: Path,
    project_dir: Path = typer.Option(Path("."), "--project-dir", file_okay=False, dir_okay=True),
    generate_eval: str = typer.Option("true", "--generate-eval"),
    parser_mode: str = typer.Option("auto", "--parser-mode"),
    resource_profile: str = typer.Option("low", "--resource-profile"),
    generation_workers: int = typer.Option(2, "--generation-workers"),
    judge_workers: int = typer.Option(1, "--judge-workers"),
    page_batch_size: int = typer.Option(100, "--page-batch-size"),
    batch_pause_seconds: float = typer.Option(2.0, "--batch-pause-seconds"),
    targets_per_chunk: int = typer.Option(3, "--targets-per-chunk"),
    include_file: list[str] = typer.Option([], "--include-file"),
    max_pdfs: int | None = typer.Option(None, "--max-pdfs"),
    max_pages_per_chunk: int | None = typer.Option(None, "--max-pages-per-chunk"),
    quality_preset: str | None = typer.Option(None, "--quality-preset"),
    min_groundedness_score: float | None = typer.Option(None, "--min-groundedness-score"),
    min_overall_score: float | None = typer.Option(None, "--min-overall-score"),
    allow_partial_export: bool = typer.Option(False, "--allow-partial-export"),
    agent: bool = typer.Option(False, "--agent"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    pdf_path = pdf_dir.resolve()
    pdf_count = len(discover_pdf_paths(pdf_path, recursive=True))
    if pdf_count < 1:
        raise typer.BadParameter("No se encontraron PDFs elegibles en la carpeta indicada.")
    if max_pdfs is not None and max_pdfs < 1:
        raise typer.BadParameter("--max-pdfs must be greater than zero.")
    if max_pages_per_chunk is not None and max_pages_per_chunk < 1:
        raise typer.BadParameter("--max-pages-per-chunk must be greater than zero.")
    parser_mode = parser_mode.strip().lower()
    if parser_mode not in {"auto", "fast", "ocr_safe"}:
        raise typer.BadParameter("Unknown parser mode. Use auto, fast, or ocr_safe.")

    init_project(project_dir)
    runner = _get_cli_job_runner(project_dir)
    agent_mode = _is_agent_mode(agent)
    job_id = runner.create_job(
        source_dir=str(pdf_path),
        project_dir=str(project_dir.resolve()),
        generate_eval=parse_bool(generate_eval),
        parser_mode=parser_mode,
        resource_profile=resource_profile,
        generation_workers=generation_workers,
        judge_workers=judge_workers,
        page_batch_size=page_batch_size,
        batch_pause_seconds=batch_pause_seconds,
        targets_per_chunk=targets_per_chunk,
        included_files=include_file or None,
        max_pdfs=max_pdfs,
        max_pages_per_chunk=max_pages_per_chunk,
        quality_preset=quality_preset,
        min_groundedness_score=min_groundedness_score,
        min_overall_score=min_overall_score,
        allow_partial_export=allow_partial_export,
        agent_mode=agent_mode,
    )
    store = get_job_store()
    launch_error: str | None = None
    try:
        _spawn_detached_job_worker(project_dir=project_dir, job_id=job_id)
    except Exception as exc:
        launch_error = str(exc)
        store.update_progress(
            job_id,
            stage="failed",
            status="failed",
            percent=1.0,
            message=f"Failed to launch worker: {exc}",
            error=str(exc),
        )

    job = store.get_job(job_id)
    if job is None:
        raise typer.Exit(code=1)

    payload = _job_payload(job)
    if json_output:
        _emit_json(payload)
        if launch_error:
            raise typer.Exit(code=1)
        return
    typer.echo(
        f"Submitted job {job.job_id}: status={job.status} stage={job.stage} "
        f"mode={payload.get('dataset_mode') or '-'} artifacts={job.artifacts_dir}"
    )
    if payload.get("note"):
        typer.echo(str(payload["note"]))
    if launch_error:
        raise typer.Exit(code=1)


@app.command()
def run(
    pdf_dir: Path,
    project_dir: Path = typer.Option(Path("."), "--project-dir", file_okay=False, dir_okay=True),
    generate_eval: str = typer.Option("true", "--generate-eval"),
    parser_mode: str = typer.Option("auto", "--parser-mode"),
    recursive: str = typer.Option("true", "--recursive"),
    resource_profile: str = typer.Option("low", "--resource-profile"),
    generation_workers: int = typer.Option(2, "--generation-workers"),
    judge_workers: int = typer.Option(1, "--judge-workers"),
    page_batch_size: int = typer.Option(100, "--page-batch-size"),
    batch_pause_seconds: float = typer.Option(2.0, "--batch-pause-seconds"),
    max_pdfs: int | None = typer.Option(None, "--max-pdfs"),
    max_pages_per_chunk: int | None = typer.Option(None, "--max-pages-per-chunk"),
    quality_preset: str | None = typer.Option(None, "--quality-preset"),
    min_groundedness_score: float | None = typer.Option(None, "--min-groundedness-score"),
    min_overall_score: float | None = typer.Option(None, "--min-overall-score"),
    resume: bool = typer.Option(False, "--resume"),
    from_phase: str | None = typer.Option(None, "--from-phase"),
    only_train: bool = typer.Option(False, "--only-train"),
    only_eval: bool = typer.Option(False, "--only-eval"),
    allow_partial_export: bool = typer.Option(False, "--allow-partial-export"),
    agent: bool = typer.Option(False, "--agent"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    run_dir = build_run_output_dir(pdf_dir)
    paths, config = _paths_and_config(project_dir, run_dir=run_dir)
    from_phase = _validate_phase_flags(from_phase, only_train, only_eval)
    generate_eval_flag = parse_bool(generate_eval)
    recursive_flag = parse_bool(recursive)
    if max_pdfs is not None and max_pdfs < 1:
        raise typer.BadParameter("--max-pdfs must be greater than zero.")
    if max_pages_per_chunk is not None and max_pages_per_chunk < 1:
        raise typer.BadParameter("--max-pages-per-chunk must be greater than zero.")
    discovered_pdfs = discover_pdf_paths(pdf_dir.resolve(), recursive=recursive_flag)
    pdf_count = len(discovered_pdfs[:max_pdfs] if max_pdfs is not None else discovered_pdfs)
    if pdf_count < 1:
        raise typer.BadParameter("No se encontraron PDFs elegibles en la carpeta indicada.")
    expected_mode = detect_dataset_mode(pdf_count)
    if not json_output:
        typer.echo(f"Detected mode: {dataset_mode_label(expected_mode)}")
        typer.echo(dataset_mode_summary(expected_mode, pdf_count=pdf_count))
        if expected_mode == "multi_document" and not generate_eval_flag:
            typer.echo(
                "Ignoring legacy --generate-eval false: multi-document mode always exports eval limpio por doc_id."
            )
        elif expected_mode == "single_document" and generate_eval_flag:
            typer.echo(
                "Ignoring legacy --generate-eval true: single-document mode exports train + review without eval limpio."
            )
    effective_generate_eval = expected_mode == "multi_document"
    config = _apply_cli_parser_mode(config, parser_mode)
    agent_mode = _is_agent_mode(agent)
    if agent_mode:
        generation_workers, judge_workers, batch_pause_seconds = _apply_agent_defaults(
            config,
            generation_workers=generation_workers,
            judge_workers=judge_workers,
            batch_pause_seconds=batch_pause_seconds,
        )
    config.generation.resource_profile = resource_profile
    config.generation.generation_workers = generation_workers
    config.generation.judge_workers = judge_workers
    config.generation.page_batch_size = page_batch_size
    config.generation.batch_pause_seconds = batch_pause_seconds
    if max_pages_per_chunk is not None:
        config.chunking.max_pages_per_chunk = max_pages_per_chunk
    config = _apply_cli_quality_overrides(
        config,
        quality_preset=quality_preset,
        min_groundedness_score=min_groundedness_score,
        min_overall_score=min_overall_score,
    )
    if allow_partial_export:
        config.export.allow_partial_export = True
    backend = build_backend(config)
    session = PipelineSession(paths=paths, config=config, backend=backend)
    completed_before = set(session.completed_phases())
    captured_output = io.StringIO()
    with ExitStack() as stack:
        if json_output:
            stack.enter_context(redirect_stdout(captured_output))
            stack.enter_context(redirect_stderr(captured_output))

        if _should_run_phase("ingest", completed=completed_before, resume=resume, from_phase=from_phase):
            document_count, chunk_count = session.ingest(pdf_dir=pdf_dir, recursive=recursive_flag, max_documents=max_pdfs)
        else:
            document_count = len(read_jsonl(paths.documents_path, DocumentRecord))
            chunk_count = len(read_jsonl(paths.chunks_path, ChunkRecord))

        if _should_run_phase("split", completed=completed_before, resume=resume, from_phase=from_phase):
            manifest = session.split()
        else:
            manifest = SplitManifest.model_validate(read_json(paths.split_path))

        train_total = len(read_jsonl(paths.generated_dir / "train.jsonl", GeneratedExample))
        train_summary_payload = read_json(paths.curated_dir / "train-summary.json")
        train_summary = (
            CuratedSummary.model_validate(train_summary_payload)
            if train_summary_payload
            else CuratedSummary(total_input=0, accepted=0, rejected=0, rejected_by_reason={})
        )
        if not only_eval:
            if _should_run_phase("generate_train", completed=completed_before, resume=resume, from_phase=from_phase):
                train_total = session.generate_split("train")
            if _should_run_phase("judge_train", completed=completed_before, resume=resume, from_phase=from_phase):
                train_summary = session.curate_split("train")

        eval_total = 0
        eval_summary = CuratedSummary(total_input=0, accepted=0, rejected=0, rejected_by_reason={})
        eval_summary_payload = read_json(paths.curated_dir / "eval-summary.json")
        if eval_summary_payload:
            eval_summary = CuratedSummary.model_validate(eval_summary_payload)
        if effective_generate_eval and manifest.has_clean_eval and not only_train:
            eval_total = len(read_jsonl(paths.generated_dir / "eval.jsonl", GeneratedExample))
            if _should_run_phase("generate_eval", completed=completed_before, resume=resume, from_phase=from_phase):
                eval_total = session.generate_split("eval")
            if _should_run_phase("judge_eval", completed=completed_before, resume=resume, from_phase=from_phase):
                eval_summary = session.curate_split("eval")
        else:
            if not (only_train and (paths.generated_dir / "eval.jsonl").exists()):
                write_jsonl([], paths.generated_dir / "eval.jsonl")
                write_jsonl([], paths.curated_dir / "eval.jsonl")
                write_json(eval_summary.model_dump(mode="json"), paths.curated_dir / "eval-summary.json")

        if _should_run_phase("export", completed=completed_before, resume=resume, from_phase=from_phase):
            train_count, eval_count, review_count = session.export()
        else:
            train_count = _jsonl_line_count(paths.exports_dir / "train.jsonl")
            eval_count = _jsonl_line_count(paths.exports_dir / "eval.jsonl")
            review_count = _jsonl_line_count(paths.exports_dir / "review_sample.jsonl")
        if _should_run_phase("report", completed=completed_before, resume=resume, from_phase=from_phase):
            report_path, _markdown = session.report()
        else:
            report_path = paths.reports_dir / "latest.md"
    payload = {
        "mode": manifest.dataset_mode,
        "parser_mode": parser_mode.strip().lower(),
        "agent_mode": agent_mode,
        "resume": resume,
        "from_phase": from_phase,
        "only_train": only_train,
        "only_eval": only_eval,
        "completed_phases": session.completed_phases(),
        "documents": document_count,
        "chunks": chunk_count,
        "pdf_limit": max_pdfs,
        "max_pages_per_chunk": config.chunking.max_pages_per_chunk,
        "train_generated": train_total,
        "train_accepted": train_summary.accepted,
        "eval_generated": eval_total,
        "eval_accepted": eval_summary.accepted,
        "exports": {
            "train": train_count,
            "eval": eval_count,
            "review": review_count,
        },
        "quality": {
            "preset": config.filters.preset,
            "min_groundedness_score": config.filters.effective_groundedness,
            "min_overall_score": config.filters.effective_overall,
        },
        "report": str(report_path),
        "output_dir": str(paths.run_dir),
    }
    if json_output:
        _emit_json(payload)
        return
    typer.echo(
        "Pipeline complete: "
        f"mode={payload['mode']} "
        f"documents={payload['documents']} chunks={payload['chunks']} "
        f"train_generated={payload['train_generated']} train_accepted={payload['train_accepted']} "
        f"eval_generated={payload['eval_generated']} eval_accepted={payload['eval_accepted']} "
        f"exports(train={train_count}, eval={eval_count}, review={review_count}) "
        f"report={report_path}"
    )


@app.command()
def jobs(
    limit: int = typer.Option(20, "--limit"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    store = get_job_store()
    records = store.list_jobs(limit=max(1, limit))
    payload = {"jobs": [_job_payload(job) for job in records]}
    if json_output:
        _emit_json(payload)
        return
    for job in records:
        typer.echo(
            f"{job.job_id} status={job.status} stage={job.stage} percent={job.percent:.2f} source={job.source_dir}"
        )


@app.command()
def status(
    job_id: str | None = typer.Option(None, "--job-id"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    store = get_job_store()
    job = store.get_job(job_id) if job_id else store.active_job()
    if job is None:
        if json_output:
            _emit_json({"error": "No active job found"})
        else:
            typer.echo("No active job found")
        raise typer.Exit(code=1)
    if json_output:
        _emit_json(_job_payload(job))
        return
    typer.echo(
        f"job={job.job_id} status={job.status} stage={job.stage} percent={job.percent:.2f} "
        f"message={job.message or '-'}"
    )


@app.command()
def events(
    job_id: str = typer.Option(..., "--job-id"),
    after_event_id: int = typer.Option(0, "--after-event-id"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    store = get_job_store()
    items = store.list_events(job_id, after_event_id=after_event_id)
    payload = {
        "job_id": job_id,
        "after_event_id": after_event_id,
        "events": [item.model_dump(mode="json") for item in items],
    }
    if json_output:
        _emit_json(payload)
        return
    for item in items:
        typer.echo(
            f"{item.event_id} status={item.status} stage={item.stage} percent={item.percent:.2f} "
            f"message={item.message or '-'}"
        )


@app.command()
def wait(
    job_id: str = typer.Option(..., "--job-id"),
    timeout_seconds: float | None = typer.Option(None, "--timeout-seconds"),
    poll_interval: float = typer.Option(1.0, "--poll-interval"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    store = get_job_store()
    started_at = time.time()
    while True:
        job = store.get_job(job_id)
        if job is None:
            if json_output:
                _emit_json({"job_id": job_id, "error": "Unknown job"})
            else:
                typer.echo(f"Unknown job '{job_id}'")
            raise typer.Exit(code=1)

        if job.status in TERMINAL_JOB_STATUSES:
            payload = _job_payload(job)
            if json_output:
                _emit_json(payload)
            else:
                typer.echo(
                    f"job={job.job_id} status={job.status} stage={job.stage} percent={job.percent:.2f} "
                    f"message={job.message or '-'}"
                )
            raise typer.Exit(code=0 if job.status == "completed" else 1)

        if timeout_seconds is not None and (time.time() - started_at) >= timeout_seconds:
            payload = _job_payload(job)
            payload["timed_out"] = True
            if json_output:
                _emit_json(payload)
            else:
                typer.echo(
                    f"Timed out waiting for {job.job_id}: status={job.status} stage={job.stage} percent={job.percent:.2f}"
                )
            raise typer.Exit(code=2)

        time.sleep(max(0.1, poll_interval))


@app.command()
def pause(
    job_id: str = typer.Option(..., "--job-id"),
    project_dir: Path = typer.Option(Path("."), "--project-dir", file_okay=False, dir_okay=True),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _ = project_dir
    store = get_job_store()
    if store.get_job(job_id) is None:
        raise typer.BadParameter(f"Unknown job '{job_id}'")
    store.set_control_action(job_id, "pause")
    if json_output:
        _emit_json({"job_id": job_id, "action": "pause"})
        return
    typer.echo(f"Pause requested for {job_id}")


@app.command()
def resume(
    job_id: str = typer.Option(..., "--job-id"),
    project_dir: Path = typer.Option(Path("."), "--project-dir", file_okay=False, dir_okay=True),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _ = project_dir
    store = get_job_store()
    if store.get_job(job_id) is None:
        raise typer.BadParameter(f"Unknown job '{job_id}'")
    store.set_control_action(job_id, "resume")
    if json_output:
        _emit_json({"job_id": job_id, "action": "resume"})
        return
    typer.echo(f"Resume requested for {job_id}")


@app.command()
def cancel(
    job_id: str = typer.Option(..., "--job-id"),
    project_dir: Path = typer.Option(Path("."), "--project-dir", file_okay=False, dir_okay=True),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _ = project_dir
    store = get_job_store()
    if store.get_job(job_id) is None:
        raise typer.BadParameter(f"Unknown job '{job_id}'")
    store.set_control_action(job_id, "cancel")
    if json_output:
        _emit_json({"job_id": job_id, "action": "cancel"})
        return
    typer.echo(f"Cancel requested for {job_id}")


@app.command("internal-run-job", hidden=True)
def internal_run_job(
    job_id: str = typer.Option(..., "--job-id"),
    project_dir: Path = typer.Option(Path("."), "--project-dir", file_okay=False, dir_okay=True),
) -> None:
    runner = _get_cli_job_runner(project_dir)
    runner.run_registered_job(job_id)


@app.command()
def verify(
    mode: str = typer.Option("mock-full", "--mode"),
    project_dir: Path = typer.Option(Path("."), "--project-dir", file_okay=False, dir_okay=True),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    if mode == "mock-full":
        summary = run_mock_full_verification()
    elif mode == "real-smoke":
        summary = run_real_smoke_verification(project_dir=project_dir, secret_store=get_secret_store())
    else:
        raise typer.BadParameter(f"Unknown verify mode '{mode}'")
    if json_output:
        _emit_json(summary)
        return
    typer.echo(f"verify {summary['mode']} ok={summary['ok']}")


@app.command()
def doctor(
    project_dir: Path = typer.Option(Path("."), "--project-dir", file_okay=False, dir_okay=True),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    payload = _doctor_payload(project_dir)
    if json_output:
        _emit_json(payload)
        return
    typer.echo(f"doctor ok={payload['ok']}")
    dependencies = payload["dependencies"]
    if isinstance(dependencies, dict):
        for name, status in dependencies.items():
            if isinstance(status, dict):
                marker = "ok" if status.get("found") else "missing"
                detail = f" path={status['path']}" if status.get("path") else ""
                typer.echo(f"- {name}: {marker}{detail}")
    for warning in payload["warnings"]:
        typer.echo(f"warning: {warning}")


@provider_app.command("list")
def provider_list(
    project_dir: Path = typer.Option(Path("."), "--project-dir", file_okay=False, dir_okay=True),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    paths, config = _paths_and_config(project_dir)
    _ = paths
    payload = {
        "active": config.providers.active,
        "providers": [
            {
                "name": name,
                "model": profile.model,
                "base_url": profile.base_url,
                "env": profile.api_key_env,
                "active": name == config.providers.active,
            }
            for name, profile in config.providers.profiles.items()
        ],
    }
    if json_output:
        _emit_json(payload)
        return
    for name, profile in config.providers.profiles.items():
        marker = "*" if name == config.providers.active else "-"
        typer.echo(f"{marker} {name}: model={profile.model} base_url={profile.base_url} env={profile.api_key_env}")


@provider_app.command("use")
def provider_use(
    provider_name: str,
    project_dir: Path = typer.Option(Path("."), "--project-dir", file_okay=False, dir_okay=True),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    paths, config = _paths_and_config(project_dir)
    if provider_name not in config.providers.profiles:
        raise typer.BadParameter(f"Unknown provider '{provider_name}'")
    config.providers.active = provider_name
    save_config(config, paths.config_path)
    if json_output:
        _emit_json({"active": provider_name})
        return
    typer.echo(f"Active provider set to {provider_name}")


@provider_app.command("set-key")
def provider_set_key(
    provider_name: str,
    project_dir: Path = typer.Option(Path("."), "--project-dir", file_okay=False, dir_okay=True),
    api_key: str | None = typer.Option(None, "--api-key"),
    stdin_input: bool = typer.Option(False, "--stdin"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    paths, config = _paths_and_config(project_dir)
    _ = paths
    if provider_name not in config.providers.profiles:
        raise typer.BadParameter(f"Unknown provider '{provider_name}'")
    if api_key and stdin_input:
        raise typer.BadParameter("Use either --api-key or --stdin, not both.")
    if stdin_input:
        secret = sys.stdin.read().strip()
        if not secret:
            raise typer.BadParameter("No API key received from stdin.")
    elif api_key:
        secret = api_key
    else:
        secret = typer.prompt("API key", hide_input=True, confirmation_prompt=True)
    store_api_key(provider_name, secret, store=get_secret_store())
    if json_output:
        _emit_json({"stored": True, "provider": provider_name})
        return
    typer.echo(f"Stored API key securely for provider {provider_name}")


@provider_app.command("test")
def provider_test(
    provider_name: str | None = typer.Argument(None),
    project_dir: Path = typer.Option(Path("."), "--project-dir", file_okay=False, dir_okay=True),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    paths, config = _paths_and_config(project_dir)
    _ = paths
    selected = provider_name or config.providers.active
    backend = build_backend(config, provider_name=selected)
    payload = backend.generate_structured(
        system_prompt="Return a valid JSON object.",
        user_prompt="Respond with ok=true and provider as a string.",
        json_schema={
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "provider": {"type": "string"},
            },
            "required": ["ok", "provider"],
            "additionalProperties": False,
        },
        session_id=f"provider-test-{selected}",
    )
    if json_output:
        _emit_json({"provider": selected, "response": payload})
        return
    typer.echo(f"Provider {selected} responded with: {payload}")


if __name__ == "__main__":
    app()
