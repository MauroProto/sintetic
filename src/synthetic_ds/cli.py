from __future__ import annotations

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import webbrowser

import typer

from synthetic_ds.config import ProjectConfig, default_config, load_config, save_config
from synthetic_ds.ingest import discover_pdf_paths
from synthetic_ds.inference import OpenAICompatibleInferenceBackend
from synthetic_ds.models import (
    CuratedSummary,
)
from synthetic_ds.pipeline import PipelineSession
from synthetic_ds.secrets import get_default_secret_store, resolve_api_key, store_api_key
from synthetic_ds.splitter import dataset_mode_label, dataset_mode_summary, detect_dataset_mode
from synthetic_ds.storage import (
    build_project_paths,
    build_run_output_dir,
    ensure_project_layout,
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


def _job_payload(job) -> dict:
    payload = job.model_dump(mode="json")
    payload["dataset_mode"] = job.config.get("dataset_mode")
    payload["note"] = job.config.get("dataset_mode_note")
    return payload


def _get_cli_job_runner(project_dir: Path):
    from synthetic_ds.job_runner import JobRunner

    return JobRunner(project_dir=project_dir, job_store=get_job_store(), secret_store=get_secret_store())


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


def build_backend(
    config: ProjectConfig,
    *,
    provider_name: str | None = None,
    store=None,
) -> OpenAICompatibleInferenceBackend:
    selected_provider = provider_name or config.providers.active
    profile = config.providers.profile_for(selected_provider)
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


def run_ingest(paths, config: ProjectConfig, *, pdf_dir: Path, recursive: bool = True) -> tuple[int, int]:
    session = PipelineSession(paths=paths, config=config)
    return session.ingest(pdf_dir=pdf_dir, recursive=recursive)


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
) -> None:
    paths, config = _paths_and_config(project_dir)
    document_count, chunk_count = run_ingest(paths, config, pdf_dir=pdf_dir, recursive=parse_bool(recursive))
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
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    pdf_path = pdf_dir.resolve()
    pdf_count = len(discover_pdf_paths(pdf_path, recursive=True))
    if pdf_count < 1:
        raise typer.BadParameter("No se encontraron PDFs elegibles en la carpeta indicada.")

    init_project(project_dir)
    runner = _get_cli_job_runner(project_dir)
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
    recursive: str = typer.Option("true", "--recursive"),
    resource_profile: str = typer.Option("low", "--resource-profile"),
    generation_workers: int = typer.Option(2, "--generation-workers"),
    judge_workers: int = typer.Option(1, "--judge-workers"),
    page_batch_size: int = typer.Option(100, "--page-batch-size"),
    batch_pause_seconds: float = typer.Option(2.0, "--batch-pause-seconds"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    run_dir = build_run_output_dir(pdf_dir)
    paths, config = _paths_and_config(project_dir, run_dir=run_dir)
    secret_store = get_secret_store()
    generate_eval_flag = parse_bool(generate_eval)
    recursive_flag = parse_bool(recursive)
    pdf_count = len(discover_pdf_paths(pdf_dir.resolve(), recursive=recursive_flag))
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
    config.generation.resource_profile = resource_profile
    config.generation.generation_workers = generation_workers
    config.generation.judge_workers = judge_workers
    config.generation.page_batch_size = page_batch_size
    config.generation.batch_pause_seconds = batch_pause_seconds
    backend = build_backend(config, store=secret_store)
    session = PipelineSession(paths=paths, config=config, backend=backend)
    captured_output = io.StringIO()
    with ExitStack() as stack:
        if json_output:
            stack.enter_context(redirect_stdout(captured_output))
            stack.enter_context(redirect_stderr(captured_output))

        document_count, chunk_count = session.ingest(pdf_dir=pdf_dir, recursive=recursive_flag)
        manifest = session.split()
        train_total = session.generate_split("train")
        train_summary = session.curate_split("train")

        eval_total = 0
        eval_summary = CuratedSummary(total_input=0, accepted=0, rejected=0, rejected_by_reason={})
        if effective_generate_eval and manifest.has_clean_eval:
            eval_total = session.generate_split("eval")
            eval_summary = session.curate_split("eval")
        else:
            write_jsonl([], paths.generated_dir / "eval.jsonl")
            write_jsonl([], paths.curated_dir / "eval.jsonl")
            write_json(eval_summary.model_dump(mode="json"), paths.curated_dir / "eval-summary.json")

        train_count, eval_count, review_count = session.export()
        report_path, _markdown = session.report()
    payload = {
        "mode": manifest.dataset_mode,
        "documents": document_count,
        "chunks": chunk_count,
        "train_generated": train_total,
        "train_accepted": train_summary.accepted,
        "eval_generated": eval_total,
        "eval_accepted": eval_summary.accepted,
        "exports": {
            "train": train_count,
            "eval": eval_count,
            "review": review_count,
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
