from __future__ import annotations

import json
import mimetypes
import time
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from synthetic_ds.app_state import JobRecord, JobStore, default_app_state_dir
from synthetic_ds.cli import get_secret_store
from synthetic_ds.config import ProjectConfig, default_config, load_config, save_config
from synthetic_ds.examples_editor import (
    EditorPaths,
    ExampleNotFound,
    accept_example,
    delete_example,
    reexport_job,
    reject_example,
    update_example,
)
from synthetic_ds.folder_picker import pick_directory
from synthetic_ds.ingest import discover_pdf_paths
from synthetic_ds.job_runner import JobRunner
from synthetic_ds.models import GeneratedExample, RejectedExample
from synthetic_ds.obs import configure_logging, log_dependency_status
from synthetic_ds.secrets import resolve_api_key, store_api_key
from synthetic_ds.splitter import dataset_mode_label, dataset_mode_note, dataset_mode_summary, detect_dataset_mode
from synthetic_ds.storage import build_project_paths, read_json, read_jsonl


WEB_DIR = Path(__file__).parent / "web"
DIST_DIR = WEB_DIR / "dist"
ASSETS_DIR = DIST_DIR / "assets"


def _job_work_dir(job: JobRecord) -> Path:
    return Path(job.artifacts_dir) / ".work" / job.job_id


def _job_curated_dir(job: JobRecord) -> Path:
    return _job_work_dir(job) / "curated"


def _safe_relative_path(root: Path, candidate: str) -> Path | None:
    target = (root / candidate).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


def create_app(
    *,
    project_dir: Path | None = None,
    job_store: JobStore | None = None,
    job_runner: JobRunner | None = None,
    secret_store=None,
) -> FastAPI:
    configure_logging()
    log_dependency_status()
    project_root = (project_dir or Path(".")).resolve()
    project_root.mkdir(parents=True, exist_ok=True)
    paths = build_project_paths(project_root)
    if not paths.config_path.exists():
        save_config(default_config(), paths.config_path)
    secret_store = secret_store or get_secret_store()
    if job_store is None:
        app_state_dir = default_app_state_dir()
        app_state_dir.mkdir(parents=True, exist_ok=True)
        store = JobStore(app_state_dir / "app.db")
    else:
        store = job_store
    runner = job_runner or JobRunner(project_dir=project_root, job_store=store, secret_store=secret_store)

    app = FastAPI(title="synthetic-ds")
    app.state.project_dir = project_root
    app.state.job_store = store
    app.state.job_runner = runner
    app.state.secret_store = secret_store
    app.state.config_path = paths.config_path

    # ----------------- Source discovery / folder picker -----------------

    @app.get("/api/source-mode")
    def api_source_mode(source_dir: str) -> JSONResponse:
        source_path = Path(source_dir).expanduser().resolve()
        pdf_count = len(discover_pdf_paths(source_path, recursive=True)) if source_path.exists() else 0
        if pdf_count < 1:
            return JSONResponse(
                {
                    "ok": False,
                    "pdf_count": 0,
                    "dataset_mode": None,
                    "label": None,
                    "message": "No se encontraron PDFs elegibles en la carpeta indicada.",
                }
            )
        dataset_mode = detect_dataset_mode(pdf_count)
        return JSONResponse(
            {
                "ok": True,
                "pdf_count": pdf_count,
                "dataset_mode": dataset_mode,
                "label": dataset_mode_label(dataset_mode),
                "message": dataset_mode_summary(dataset_mode, pdf_count=pdf_count),
                "note": dataset_mode_note(dataset_mode),
            }
        )

    @app.post("/api/pick-folder")
    def api_pick_folder() -> JSONResponse:
        return JSONResponse({"path": pick_directory() or ""})

    @app.get("/api/pdfs")
    def api_list_pdfs(source_dir: str) -> JSONResponse:
        source_path = Path(source_dir).expanduser().resolve()
        if not source_path.exists():
            return JSONResponse({"items": [], "count": 0, "root": str(source_path), "ok": False})
        pdf_paths = discover_pdf_paths(source_path, recursive=True)
        items: list[dict[str, Any]] = []
        for pdf in pdf_paths:
            try:
                rel = str(pdf.relative_to(source_path))
            except ValueError:
                rel = pdf.name
            stat = pdf.stat()
            items.append(
                {
                    "path": rel,
                    "size": stat.st_size,
                    "modified_at": time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)
                    ),
                }
            )
        return JSONResponse(
            {"items": items, "count": len(items), "root": str(source_path), "ok": True}
        )

    # ----------------- Providers -----------------

    @app.get("/api/health")
    def api_health() -> JSONResponse:
        deps = log_dependency_status()
        pool = runner.pool_status() if hasattr(runner, "pool_status") else {}
        return JSONResponse({"ok": True, "dependencies": deps, "pool": pool})

    @app.get("/api/providers")
    def api_providers() -> JSONResponse:
        config = load_config(paths.config_path)
        keys_present: dict[str, bool] = {}
        for name, profile in config.providers.profiles.items():
            keys_present[name] = bool(resolve_api_key(name, profile.api_key_env, store=secret_store))
        return JSONResponse(
            {
                "active": config.providers.active,
                "profiles": {
                    name: profile.model_dump(mode="json") for name, profile in config.providers.profiles.items()
                },
                "keys_present": keys_present,
            }
        )

    @app.post("/api/provider/key")
    def api_set_provider_key(
        provider_name: str = Form(...),
        api_key: str = Form(...),
    ) -> JSONResponse:
        store_api_key(provider_name, api_key, store=secret_store)
        return JSONResponse({"stored": True, "provider": provider_name})

    @app.post("/api/provider/active")
    def api_set_active_provider(provider: str = Form(...)) -> JSONResponse:
        config = load_config(paths.config_path)
        if provider not in config.providers.profiles:
            raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'")
        config.providers.active = provider
        save_config(config, paths.config_path)
        return JSONResponse({"active": provider})

    # ----------------- Config (YAML) -----------------

    @app.get("/api/config")
    def api_get_config() -> JSONResponse:
        config = load_config(paths.config_path)
        raw_yaml = paths.config_path.read_text(encoding="utf-8") if paths.config_path.exists() else ""
        return JSONResponse(
            {
                "yaml": raw_yaml,
                "config": config.model_dump(mode="json"),
            }
        )

    @app.post("/api/config")
    async def api_save_config(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"JSON inv\u00e1lido: {exc}")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Payload debe ser un objeto JSON")
        source: dict[str, Any] | None = None
        if "yaml" in payload and isinstance(payload["yaml"], str):
            try:
                parsed = yaml.safe_load(payload["yaml"])
            except yaml.YAMLError as exc:
                raise HTTPException(status_code=400, detail=f"YAML inv\u00e1lido: {exc}")
            if not isinstance(parsed, dict):
                raise HTTPException(status_code=400, detail="El YAML debe representar un objeto/mapa.")
            source = parsed
        elif "config" in payload and isinstance(payload["config"], dict):
            source = payload["config"]
        else:
            raise HTTPException(status_code=400, detail="Se esperaba 'yaml' (string) o 'config' (dict)")
        try:
            config = ProjectConfig.model_validate(source)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors())
        save_config(config, paths.config_path)
        raw_yaml = paths.config_path.read_text(encoding="utf-8")
        return JSONResponse({"yaml": raw_yaml, "config": config.model_dump(mode="json")})

    # ----------------- Jobs -----------------

    @app.get("/api/jobs")
    def api_list_jobs(limit: int = 20) -> JSONResponse:
        jobs = store.list_jobs(limit=max(1, min(limit, 100)))
        return JSONResponse([job.model_dump(mode="json") for job in jobs])

    @app.post("/api/jobs")
    def api_create_job(
        source_dir: str = Form(...),
        generate_eval: str = Form("true"),
        parser_mode: str = Form("auto"),
        resource_profile: str = Form("low"),
        generation_workers: int = Form(2),
        judge_workers: int = Form(1),
        page_batch_size: int = Form(100),
        batch_pause_seconds: float = Form(2.0),
        targets_per_chunk: int = Form(3),
        included_files: str | None = Form(None),
    ) -> JSONResponse:
        generate_eval_flag = generate_eval.strip().lower() in {"1", "true", "yes", "on"}
        source_path = Path(source_dir).resolve()
        all_paths = discover_pdf_paths(source_path, recursive=True)
        if len(all_paths) < 1:
            return JSONResponse(
                {"error": "No se encontraron PDFs elegibles en la carpeta indicada."},
                status_code=409,
            )

        parsed_included: list[str] | None = None
        if included_files:
            try:
                parsed = json.loads(included_files)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="included_files debe ser JSON v\u00e1lido")
            if not isinstance(parsed, list):
                raise HTTPException(status_code=400, detail="included_files debe ser una lista")
            parsed_included = [str(item) for item in parsed if isinstance(item, str)]

        effective_count = len(parsed_included) if parsed_included is not None else len(all_paths)
        if effective_count < 1:
            return JSONResponse(
                {"error": "Debes incluir al menos un PDF."}, status_code=409,
            )
        dataset_mode = detect_dataset_mode(effective_count)
        try:
            job_id = runner.start_job(
                source_dir=source_dir,
                project_dir=str(project_root),
                generate_eval=generate_eval_flag,
                parser_mode=parser_mode,
                resource_profile=resource_profile,
                generation_workers=generation_workers,
                judge_workers=judge_workers,
                page_batch_size=page_batch_size,
                batch_pause_seconds=batch_pause_seconds,
                targets_per_chunk=targets_per_chunk,
                included_files=parsed_included,
            )
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        job = store.get_job(job_id)
        assert job is not None
        return JSONResponse(
            {
                "job_id": job_id,
                "status": job.status,
                "stage": job.stage,
                "dataset_mode": dataset_mode,
                "dataset_mode_label": dataset_mode_label(dataset_mode),
                "note": dataset_mode_summary(dataset_mode, pdf_count=effective_count),
            }
        )

    @app.get("/api/jobs/{job_id}")
    def api_job(job_id: str) -> JSONResponse:
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        events = [event.model_dump(mode="json") for event in store.list_events(job_id)]
        payload = job.model_dump(mode="json")
        payload["events"] = events
        return JSONResponse(payload)

    @app.post("/api/jobs/{job_id}/{action}")
    def api_job_action(job_id: str, action: str) -> JSONResponse:
        if action not in {"pause", "resume", "cancel"}:
            raise HTTPException(status_code=400, detail="Unsupported action")
        runner.control_job(job_id=job_id, action=action)
        return JSONResponse({"job_id": job_id, "action": action})

    @app.get("/api/jobs/{job_id}/events")
    def api_job_events(job_id: str) -> StreamingResponse:
        if store.get_job(job_id) is None:
            raise HTTPException(status_code=404, detail="Job not found")

        def event_stream():
            last_seen = 0
            idle_cycles = 0
            while True:
                events = store.list_events(job_id, after_event_id=last_seen)
                if events:
                    idle_cycles = 0
                    for event in events:
                        last_seen = event.event_id
                        current_job = store.get_job(job_id)
                        payload = event.model_dump(mode="json")
                        payload["stats"] = current_job.stats if current_job else {}
                        yield f"data: {json.dumps(payload)}\n\n"
                        if event.status in {"completed", "failed", "cancelled"}:
                            return
                else:
                    idle_cycles += 1
                    yield ": keep-alive\n\n"
                if idle_cycles > 60:
                    return
                time.sleep(1)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    # ----------------- Examples (curated) -----------------

    @app.get("/api/jobs/{job_id}/examples")
    def api_job_examples(
        job_id: str,
        split: str | None = None,
        accepted: str | None = None,
        kind: str | None = None,
        score_min: float | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> JSONResponse:
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        curated_dir = _job_curated_dir(job)
        available_splits: list[str] = []
        for candidate in ("train", "eval"):
            accepted_path = curated_dir / f"{candidate}.jsonl"
            rejected_path = curated_dir / f"{candidate}-rejected.jsonl"
            if accepted_path.exists() or rejected_path.exists():
                available_splits.append(candidate)

        accepted_filter: bool | None = None
        if accepted is not None:
            normalized = accepted.strip().lower()
            if normalized in {"1", "true", "yes"}:
                accepted_filter = True
            elif normalized in {"0", "false", "no"}:
                accepted_filter = False

        target_splits: list[str]
        if split:
            target_splits = [split]
        else:
            target_splits = available_splits or ["train"]

        items: list[dict[str, Any]] = []
        for target_split in target_splits:
            if accepted_filter is None or accepted_filter is True:
                accepted_path = curated_dir / f"{target_split}.jsonl"
                if accepted_path.exists():
                    for example in read_jsonl(accepted_path, GeneratedExample):
                        items.append(
                            {
                                **example.model_dump(mode="json"),
                                "split": target_split,
                                "accepted": True,
                                "reason": None,
                            }
                        )
            if accepted_filter is None or accepted_filter is False:
                rejected_path = curated_dir / f"{target_split}-rejected.jsonl"
                if rejected_path.exists():
                    for rejection in read_jsonl(rejected_path, RejectedExample):
                        items.append(
                            {
                                **rejection.example.model_dump(mode="json"),
                                "split": target_split,
                                "accepted": False,
                                "reason": rejection.reason,
                            }
                        )

        if kind:
            items = [item for item in items if str(item.get("question_type")).lower() == kind.lower()]
        if score_min is not None:
            items = [
                item
                for item in items
                if (item.get("judge_score") or {}).get("overall", 0.0) >= score_min
            ]

        total = len(items)
        start = max(0, offset)
        end = start + max(1, min(limit, 200))
        paged = items[start:end]
        return JSONResponse(
            {
                "total": total,
                "limit": limit,
                "offset": offset,
                "items": paged,
                "filters": {
                    "split": split,
                    "accepted": accepted_filter,
                    "kind": kind,
                    "score_min": score_min,
                },
                "available_splits": available_splits,
            }
        )

    # ----------------- Example editor -----------------

    def _load_active_config() -> ProjectConfig:
        return load_config(paths.config_path)

    def _editor_for(job_id: str) -> EditorPaths:
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return EditorPaths.for_job(job)

    @app.patch("/api/jobs/{job_id}/examples/{example_id}")
    async def api_patch_example(job_id: str, example_id: str, request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"JSON inv\u00e1lido: {exc}")
        split = body.get("split") or "train"
        patch = body.get("patch") or {}
        editor = _editor_for(job_id)
        try:
            result = update_example(editor, split=split, example_id=example_id, patch=patch)
        except ExampleNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        totals = reexport_job(editor, _load_active_config())
        return JSONResponse({**result, "totals": totals})

    @app.delete("/api/jobs/{job_id}/examples/{example_id}")
    def api_delete_example(job_id: str, example_id: str, split: str = "train") -> JSONResponse:
        editor = _editor_for(job_id)
        try:
            result = delete_example(editor, split=split, example_id=example_id)
        except ExampleNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        totals = reexport_job(editor, _load_active_config())
        return JSONResponse({**result, "totals": totals})

    @app.post("/api/jobs/{job_id}/examples/{example_id}/accept")
    def api_accept_example(job_id: str, example_id: str, split: str = Form("train")) -> JSONResponse:
        editor = _editor_for(job_id)
        try:
            result = accept_example(editor, split=split, example_id=example_id)
        except ExampleNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        totals = reexport_job(editor, _load_active_config())
        return JSONResponse({**result, "totals": totals})

    @app.post("/api/jobs/{job_id}/examples/{example_id}/reject")
    def api_reject_example(
        job_id: str, example_id: str, split: str = Form("train"), reason: str = Form("manual_rejection")
    ) -> JSONResponse:
        editor = _editor_for(job_id)
        try:
            result = reject_example(editor, split=split, example_id=example_id, reason=reason)
        except ExampleNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        totals = reexport_job(editor, _load_active_config())
        return JSONResponse({**result, "totals": totals})

    # ----------------- Consolidated examples (across all jobs) -----------------

    @app.get("/api/examples")
    def api_examples_dashboard(
        accepted: str | None = None,
        kind: str | None = None,
        search: str | None = None,
        score_min: float | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> JSONResponse:
        jobs = store.list_jobs(limit=100)
        accepted_filter: bool | None = None
        if accepted is not None:
            normalized = accepted.strip().lower()
            if normalized in {"1", "true", "yes"}:
                accepted_filter = True
            elif normalized in {"0", "false", "no"}:
                accepted_filter = False

        items: list[dict[str, Any]] = []
        per_job_stats: dict[str, dict[str, int]] = {}
        for job in jobs:
            curated_dir = _job_curated_dir(job)
            if not curated_dir.exists():
                continue
            per_job_stats[job.job_id] = {"accepted": 0, "rejected": 0}
            for split in ("train", "eval"):
                acc_path = curated_dir / f"{split}.jsonl"
                rej_path = curated_dir / f"{split}-rejected.jsonl"
                if (accepted_filter is None or accepted_filter is True) and acc_path.exists():
                    for example in read_jsonl(acc_path, GeneratedExample):
                        per_job_stats[job.job_id]["accepted"] += 1
                        items.append(
                            {
                                **example.model_dump(mode="json"),
                                "split": split,
                                "accepted": True,
                                "reason": None,
                                "job_id": job.job_id,
                                "source_doc": example.source_doc,
                            }
                        )
                if (accepted_filter is None or accepted_filter is False) and rej_path.exists():
                    for rejection in read_jsonl(rej_path, RejectedExample):
                        per_job_stats[job.job_id]["rejected"] += 1
                        items.append(
                            {
                                **rejection.example.model_dump(mode="json"),
                                "split": split,
                                "accepted": False,
                                "reason": rejection.reason,
                                "job_id": job.job_id,
                                "source_doc": rejection.example.source_doc,
                            }
                        )
        if kind:
            items = [item for item in items if str(item.get("question_type")).lower() == kind.lower()]
        if score_min is not None:
            items = [
                item
                for item in items
                if (item.get("judge_score") or {}).get("overall", 0.0) >= score_min
            ]
        if search:
            query = search.lower()
            items = [
                item
                for item in items
                if query in (item.get("question") or "").lower()
                or query in (item.get("answer") or "").lower()
                or query in (item.get("source_doc") or "").lower()
            ]

        total = len(items)
        start = max(0, offset)
        end = start + max(1, min(limit, 500))
        paged = items[start:end]

        all_types: dict[str, int] = {}
        score_sum = 0.0
        score_count = 0
        for item in items:
            qt = str(item.get("question_type", "unknown"))
            all_types[qt] = all_types.get(qt, 0) + 1
            score = (item.get("judge_score") or {}).get("overall")
            if isinstance(score, (int, float)):
                score_sum += float(score)
                score_count += 1

        return JSONResponse(
            {
                "total": total,
                "limit": limit,
                "offset": offset,
                "items": paged,
                "aggregate": {
                    "types": all_types,
                    "avg_score": round(score_sum / score_count, 3) if score_count else 0.0,
                    "per_job": per_job_stats,
                },
                "filters": {
                    "accepted": accepted_filter,
                    "kind": kind,
                    "score_min": score_min,
                    "search": search,
                },
            }
        )

    # ----------------- Metrics -----------------

    @app.get("/api/jobs/{job_id}/metrics")
    def api_job_metrics(job_id: str) -> JSONResponse:
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        work_dir = _job_work_dir(job)
        curated_dir = _job_curated_dir(job)
        progress_payload = read_json(work_dir / "progress.json")

        summaries: dict[str, Any] = {}
        type_distribution: dict[str, dict[str, int]] = {"train": {}, "eval": {}}
        score_distribution: dict[str, dict[str, list[float]]] = {
            "train": {"relevance": [], "groundedness": [], "overall": []},
            "eval": {"relevance": [], "groundedness": [], "overall": []},
        }
        acceptance: dict[str, dict[str, int]] = {
            "train": {"accepted": 0, "rejected": 0},
            "eval": {"accepted": 0, "rejected": 0},
        }

        for split_name in ("train", "eval"):
            summary_path = curated_dir / f"{split_name}-summary.json"
            if summary_path.exists():
                summaries[split_name] = read_json(summary_path)

            accepted_path = curated_dir / f"{split_name}.jsonl"
            if accepted_path.exists():
                for example in read_jsonl(accepted_path, GeneratedExample):
                    acceptance[split_name]["accepted"] += 1
                    qtype = str(example.question_type or "unknown")
                    type_distribution[split_name][qtype] = type_distribution[split_name].get(qtype, 0) + 1
                    if example.judge_score:
                        score_distribution[split_name]["relevance"].append(example.judge_score.relevance)
                        score_distribution[split_name]["groundedness"].append(example.judge_score.groundedness)
                        score_distribution[split_name]["overall"].append(example.judge_score.overall)

            rejected_path = curated_dir / f"{split_name}-rejected.jsonl"
            if rejected_path.exists():
                for rejection in read_jsonl(rejected_path, RejectedExample):
                    acceptance[split_name]["rejected"] += 1
                    qtype = str(rejection.example.question_type or "unknown")
                    type_distribution[split_name][qtype] = type_distribution[split_name].get(qtype, 0) + 1

        return JSONResponse(
            {
                "job_id": job_id,
                "progress": progress_payload,
                "summaries": summaries,
                "type_distribution": type_distribution,
                "score_distribution": score_distribution,
                "acceptance": acceptance,
            }
        )

    # ----------------- Artifacts -----------------

    @app.get("/api/jobs/{job_id}/artifacts")
    def api_job_artifacts(job_id: str) -> JSONResponse:
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        root = Path(job.artifacts_dir)
        items: list[dict[str, Any]] = []
        if root.exists():
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(root)
                if any(part.startswith(".") for part in relative.parts):
                    continue
                stat = path.stat()
                items.append(
                    {
                        "path": str(relative),
                        "size": stat.st_size,
                        "modified_at": time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)
                        ),
                    }
                )
        return JSONResponse({"job_id": job_id, "root": str(root), "items": items})

    @app.get("/api/jobs/{job_id}/artifacts/file")
    def api_job_artifact_file(job_id: str, path: str) -> FileResponse:
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        root = Path(job.artifacts_dir)
        target = _safe_relative_path(root, path)
        if target is None or not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="Artifact not found")
        guessed, _ = mimetypes.guess_type(str(target))
        return FileResponse(
            str(target),
            media_type=guessed or "application/octet-stream",
            filename=target.name,
        )

    # ----------------- Legacy redirects -----------------

    @app.get("/open/{job_id}")
    def open_run(job_id: str) -> RedirectResponse:
        return RedirectResponse(url=f"/runs/{job_id}", status_code=303)

    # ----------------- SPA static hosting -----------------

    if ASSETS_DIR.exists():
        app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

    public_static_files: list[Path] = []
    if DIST_DIR.exists():
        for candidate in DIST_DIR.iterdir():
            if candidate.is_file() and candidate.name != "index.html":
                public_static_files.append(candidate)

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str, request: Request):
        if full_path.startswith("api/") or full_path.startswith("open/"):
            raise HTTPException(status_code=404, detail="Not found")
        index_file = DIST_DIR / "index.html"
        if full_path:
            candidate = _safe_relative_path(DIST_DIR, full_path)
            if candidate and candidate.is_file():
                guessed, _ = mimetypes.guess_type(str(candidate))
                return FileResponse(str(candidate), media_type=guessed or "application/octet-stream")
        if not index_file.exists():
            return PlainTextResponse(
                "Frontend no compilado todav\u00eda.\n"
                "Ejecut\u00e1 `pnpm install && pnpm build` dentro de src/synthetic_ds/web/frontend y reinici\u00e1 el comando.",
                status_code=503,
            )
        return HTMLResponse(index_file.read_text(encoding="utf-8"))

    return app
