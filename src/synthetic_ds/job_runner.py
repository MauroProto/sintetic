from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from synthetic_ds.app_state import JobStore
from synthetic_ds.cli import (
    _paths_and_config,
    build_backend,
)
from synthetic_ds.config import ProjectConfig
from synthetic_ds.ingest import discover_pdf_paths
from synthetic_ds.models import ChunkRecord
from synthetic_ds.obs import get_logger, log_event
from synthetic_ds.pipeline import JobCancelledError, PipelineSession
from synthetic_ds.splitter import dataset_mode_summary, detect_dataset_mode
from synthetic_ds.storage import build_run_output_dir, read_jsonl


logger = get_logger("job_runner")


def _default_max_concurrent() -> int:
    try:
        return max(1, int(os.environ.get("SYNTHETIC_DS_MAX_JOBS", "2")))
    except ValueError:
        return 2


class JobRunner:
    """Pool de jobs con cupo configurable y cola FIFO para exceso.

    Se mantuvo compatibilidad total con la API previa:
    * ``start_job`` siempre devuelve un ``job_id`` inmediato.
    * Si hay cupo libre se lanza el thread worker; si no, queda ``queued``
      en el store y un scheduler lo despacha cuando se libere un cupo.
    * ``control_job`` (pause/resume/cancel) sigue funcionando por ``job_id``.
    """

    def __init__(
        self,
        *,
        project_dir: Path,
        job_store: JobStore,
        secret_store: Any | None = None,
        max_concurrent_jobs: int | None = None,
    ) -> None:
        self.project_dir = project_dir.resolve()
        self.job_store = job_store
        self.secret_store = secret_store
        self.max_concurrent_jobs = max(1, max_concurrent_jobs or _default_max_concurrent())
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}
        self._queue: list[str] = []  # FIFO de job_id en estado "queued"

    @property
    def active_count(self) -> int:
        with self._lock:
            return sum(1 for thread in self._threads.values() if thread.is_alive())

    def pool_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "max_concurrent_jobs": self.max_concurrent_jobs,
                "running": [jid for jid, t in self._threads.items() if t.is_alive()],
                "queued": list(self._queue),
            }

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
    ) -> str:
        with self._lock:
            job_id, ingest_path, effective_generate_eval, config, run_dir = self._register_job(
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
            )

            has_slot = sum(1 for t in self._threads.values() if t.is_alive()) < self.max_concurrent_jobs
            if has_slot:
                self._launch_worker(
                    job_id=job_id,
                    source_path=ingest_path,
                    generate_eval=effective_generate_eval,
                    config=config,
                    run_dir=run_dir,
                )
                log_event(logger, logging.INFO, "job_started", job_id=job_id, queued_len=len(self._queue))
            else:
                self._queue.append(job_id)
                self.job_store.update_progress(
                    job_id,
                    stage="queued",
                    status="queued",
                    percent=0.0,
                    message=f"En cola (posición {len(self._queue)})",
                )
                log_event(logger, logging.INFO, "job_queued", job_id=job_id, queue_len=len(self._queue))
            return job_id

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
    ) -> str:
        with self._lock:
            job_id, _ingest_path, _generate_eval, _config, _run_dir = self._register_job(
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
            )
            return job_id

    def _register_job(
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
    ) -> tuple[str, Path, bool, ProjectConfig, Path]:
        source_path = Path(source_dir).resolve()
        job_id = uuid.uuid4().hex[:12]
        run_dir = build_run_output_dir(source_path)
        paths, config = _paths_and_config(Path(project_dir), run_dir=run_dir, work_subdir=job_id)
        config = self._apply_parser_mode(config, parser_mode)
        all_paths = discover_pdf_paths(source_path, recursive=True)
        if len(all_paths) < 1:
            raise RuntimeError("No se encontraron PDFs elegibles en la carpeta indicada.")

        ingest_path = source_path
        selection_dir_str: str | None = None
        if included_files is not None:
            selected = self._resolve_included_files(source_path, all_paths, included_files)
            if len(selected) < 1:
                raise RuntimeError("Debes incluir al menos un PDF.")
            ingest_path = self._materialize_selection(run_dir=run_dir, job_id=job_id, files=selected)
            selection_dir_str = str(ingest_path)
            pdf_count = len(selected)
        else:
            pdf_count = len(all_paths)
        dataset_mode = detect_dataset_mode(pdf_count)
        effective_generate_eval = dataset_mode == "multi_document"
        config.generation.resource_profile = resource_profile
        config.generation.generation_workers = generation_workers or config.generation.generation_workers
        config.generation.judge_workers = judge_workers or config.generation.judge_workers
        config.generation.page_batch_size = max(1, page_batch_size)
        config.generation.batch_pause_seconds = max(0.0, batch_pause_seconds)
        config.generation.targets_per_chunk = max(1, targets_per_chunk)
        profile = config.providers.profile_for()
        job_id = self.job_store.create_job(
            job_id=job_id,
            source_dir=source_dir,
            provider=config.providers.active,
            model=profile.model,
            config={
                "generate_eval": effective_generate_eval,
                "generate_eval_requested": generate_eval,
                "dataset_mode": dataset_mode,
                "dataset_mode_note": dataset_mode_summary(dataset_mode, pdf_count=pdf_count),
                "parser_mode": parser_mode,
                "resource_profile": config.generation.resource_profile,
                "generation_workers": config.generation.generation_workers,
                "judge_workers": config.generation.judge_workers,
                "page_batch_size": config.generation.page_batch_size,
                "batch_pause_seconds": config.generation.batch_pause_seconds,
                "targets_per_chunk": config.generation.targets_per_chunk,
                "included_files": included_files if included_files is not None else None,
                "selection_dir": selection_dir_str,
                "pdf_count": pdf_count,
            },
            artifacts_dir=str(paths.run_dir),
        )
        return job_id, ingest_path, effective_generate_eval, config, run_dir

    def _resolve_included_files(
        self, source_path: Path, all_paths: list[Path], included: list[str]
    ) -> list[Path]:
        allowed = {p.resolve() for p in all_paths}
        selected: list[Path] = []
        for item in included:
            candidate = (source_path / item).resolve()
            if candidate in allowed:
                selected.append(candidate)
        return selected

    def _materialize_selection(self, *, run_dir: Path, job_id: str, files: list[Path]) -> Path:
        selection_dir = run_dir / ".selection" / job_id
        selection_dir.mkdir(parents=True, exist_ok=True)
        used_names: set[str] = set()
        for source in files:
            name = source.name
            if name in used_names:
                stem = source.stem
                suffix = source.suffix
                counter = 1
                while f"{stem}-{counter}{suffix}" in used_names:
                    counter += 1
                name = f"{stem}-{counter}{suffix}"
            used_names.add(name)
            link_path = selection_dir / name
            if link_path.exists() or link_path.is_symlink():
                link_path.unlink()
            try:
                link_path.symlink_to(source)
            except OSError:
                import shutil as _shutil
                _shutil.copy2(source, link_path)
        return selection_dir

    def _launch_worker(
        self,
        *,
        job_id: str,
        source_path: Path,
        generate_eval: bool,
        config: ProjectConfig,
        run_dir: Path,
    ) -> None:
        worker = threading.Thread(
            target=self._run_job,
            args=(job_id, source_path, generate_eval, config, run_dir),
            daemon=True,
            name=f"synthetic-ds-{job_id}",
        )
        self._threads[job_id] = worker
        worker.start()

    def _dispatch_next_queued(self) -> None:
        """Si hay cupo libre y jobs en cola, lanza el siguiente.

        Debe llamarse con ``self._lock`` tomado.
        """
        while self._queue and sum(1 for t in self._threads.values() if t.is_alive()) < self.max_concurrent_jobs:
            next_job_id = self._queue.pop(0)
            try:
                config, source_path, generate_eval, run_dir = self._config_for_job(next_job_id)
            except Exception as exc:
                log_event(
                    logger,
                    logging.ERROR,
                    "queued_job_dispatch_failed",
                    job_id=next_job_id,
                    exc=str(exc)[:200],
                )
                self.job_store.update_progress(
                    next_job_id,
                    stage="failed",
                    status="failed",
                    percent=1.0,
                    message=str(exc),
                    error=str(exc),
                )
                continue
            self._launch_worker(
                job_id=next_job_id,
                source_path=source_path,
                generate_eval=generate_eval,
                config=config,
                run_dir=run_dir,
            )
            log_event(logger, logging.INFO, "queued_job_started", job_id=next_job_id)

    def _apply_parser_mode(self, config: ProjectConfig, parser_mode: str) -> ProjectConfig:
        updated = config.model_copy(deep=True)
        if parser_mode == "fast":
            updated.parsing.primary_parser = "pymupdf"
            updated.parsing.fallback_parser = "pymupdf"
            updated.parsing.enable_ocr = False
            updated.parsing.render_page_images = False
        elif parser_mode == "ocr_safe":
            updated.parsing.primary_parser = "docling"
            updated.parsing.fallback_parser = "pymupdf"
            updated.parsing.enable_ocr = True
            updated.parsing.render_page_images = True
        return updated

    def _config_for_job(self, job_id: str) -> tuple[ProjectConfig, Path, bool, Path]:
        job = self.job_store.get_job(job_id)
        if job is None:
            raise RuntimeError(f"Unknown job '{job_id}'")
        run_dir = Path(job.artifacts_dir)
        paths, config = _paths_and_config(self.project_dir, run_dir=run_dir, work_subdir=job_id)
        parser_mode = job.config.get("parser_mode", "auto")
        config = self._apply_parser_mode(config, parser_mode)
        config.generation.resource_profile = job.config.get("resource_profile", config.generation.resource_profile)
        config.generation.generation_workers = job.config.get("generation_workers", config.generation.generation_workers)
        config.generation.judge_workers = job.config.get("judge_workers", config.generation.judge_workers)
        config.generation.page_batch_size = int(job.config.get("page_batch_size", config.generation.page_batch_size))
        config.generation.batch_pause_seconds = float(
            job.config.get("batch_pause_seconds", config.generation.batch_pause_seconds)
        )
        config.generation.targets_per_chunk = int(
            job.config.get("targets_per_chunk", config.generation.targets_per_chunk)
        )
        generate_eval = bool(job.config.get("generate_eval", True))
        selection_dir = job.config.get("selection_dir")
        ingest_source = Path(selection_dir) if selection_dir else Path(job.source_dir).resolve()
        return config, ingest_source, generate_eval, run_dir

    def run_registered_job(self, job_id: str) -> None:
        config, source_path, generate_eval, run_dir = self._config_for_job(job_id)
        self._run_job(job_id, source_path, generate_eval, config, run_dir)

    def control_job(self, *, job_id: str, action: str) -> None:
        if action not in {"pause", "resume", "cancel"}:
            raise RuntimeError(f"Unsupported action '{action}'")

        if action == "cancel":
            # Si el job estaba en cola lo quitamos y marcamos cancelado sin thread
            with self._lock:
                if job_id in self._queue:
                    self._queue.remove(job_id)
                    self.job_store.update_progress(
                        job_id,
                        stage="cancelled",
                        status="cancelled",
                        percent=1.0,
                        message="Cancelled while queued",
                        error="Cancelled by user",
                    )
                    log_event(logger, logging.INFO, "queued_job_cancelled", job_id=job_id)
                    return
            self.job_store.set_control_action(job_id, "cancel")
            return

        if action == "pause":
            self.job_store.set_control_action(job_id, "pause")
            return

        # resume
        with self._lock:
            self.job_store.set_control_action(job_id, "resume")
            existing = self._threads.get(job_id)
            if existing is not None and existing.is_alive():
                return
            # Lanzar nuevo worker si hay cupo; si no, encolar
            config, source_path, generate_eval, run_dir = self._config_for_job(job_id)
            if sum(1 for t in self._threads.values() if t.is_alive()) < self.max_concurrent_jobs:
                self._launch_worker(
                    job_id=job_id,
                    source_path=source_path,
                    generate_eval=generate_eval,
                    config=config,
                    run_dir=run_dir,
                )
            else:
                if job_id not in self._queue:
                    self._queue.append(job_id)
                self.job_store.update_progress(
                    job_id,
                    stage="queued",
                    status="queued",
                    percent=0.0,
                    message=f"Resume en cola (posición {self._queue.index(job_id) + 1})",
                )

    def _check_control(self, *, job_id: str, stage: str, percent: float, stats: dict[str, Any] | None = None) -> None:
        action = self.job_store.get_control_action(job_id)
        if action == "cancel":
            self.job_store.clear_control_action(job_id)
            self.job_store.update_progress(
                job_id,
                stage="cancelled",
                status="cancelled",
                percent=percent,
                message="Cancelled by user",
                error="Cancelled by user",
                stats=stats,
            )
            raise JobCancelledError("Cancelled by user")
        if action != "pause":
            return

        self.job_store.update_progress(
            job_id,
            stage=stage,
            status="paused",
            percent=percent,
            message="Paused by user",
            stats=stats,
        )
        while True:
            time.sleep(0.25)
            action = self.job_store.get_control_action(job_id)
            if action == "cancel":
                self.job_store.clear_control_action(job_id)
                self.job_store.update_progress(
                    job_id,
                    stage="cancelled",
                    status="cancelled",
                    percent=percent,
                    message="Cancelled by user",
                    error="Cancelled by user",
                    stats=stats,
                )
                raise JobCancelledError("Cancelled by user")
            if action in {None, "resume"}:
                self.job_store.clear_control_action(job_id)
                self.job_store.update_progress(
                    job_id,
                    stage=stage,
                    status="resuming",
                    percent=percent,
                    message="Resuming job",
                    stats=stats,
                )
                return

    def _chunk_batches(
        self,
        chunks: list[ChunkRecord],
        allowed_doc_ids: set[str],
        *,
        page_batch_size: int,
    ) -> list[list[str]]:
        ordered_chunks = [chunk for chunk in chunks if chunk.doc_id in allowed_doc_ids]
        if not ordered_chunks:
            return []
        batches: list[list[str]] = []
        current_batch: list[str] = []
        current_pages: set[tuple[str, int]] = set()
        for chunk in ordered_chunks:
            chunk_pages = {
                (chunk.doc_id, page_number)
                for page_number in range(chunk.page_range[0], chunk.page_range[1] + 1)
            }
            prospective_pages = current_pages | chunk_pages
            if current_batch and len(prospective_pages) > page_batch_size:
                batches.append(current_batch)
                current_batch = []
                current_pages = set()
            current_batch.append(chunk.chunk_id)
            current_pages |= chunk_pages
        if current_batch:
            batches.append(current_batch)
        return batches

    def _run_batched_generation(
        self,
        *,
        job_id: str,
        session: PipelineSession,
        paths,
        config: ProjectConfig,
        split_name: str,
        split_doc_ids: list[str],
        percent_start: float,
        percent_end: float,
    ) -> int:
        self._check_control(job_id=job_id, stage=f"generate_{split_name}", percent=percent_start)
        chunks = read_jsonl(paths.chunks_path, ChunkRecord)
        batches = self._chunk_batches(
            chunks,
            set(split_doc_ids),
            page_batch_size=config.generation.page_batch_size,
        )
        total_examples = 0
        if not batches:
            return total_examples
        chunk_map = {chunk.chunk_id: chunk for chunk in chunks}
        started_at = time.time()
        for index, batch_chunk_ids in enumerate(batches, start=1):
            batch_pages = sorted(
                {
                    (chunk_map[chunk_id].doc_id, page_number)
                    for chunk_id in batch_chunk_ids
                    if chunk_id in chunk_map
                    for page_number in range(chunk_map[chunk_id].page_range[0], chunk_map[chunk_id].page_range[1] + 1)
                }
            )
            total_examples = session.generate_split(split_name, chunk_ids=batch_chunk_ids)
            progress = percent_start + ((percent_end - percent_start) * index / len(batches))
            stats = session.stats_snapshot()
            pages_processed = int(stats.get("pages_processed", 0)) + len(batch_pages)
            eta_seconds = ((time.time() - started_at) / index) * max(0, len(batches) - index)
            session._update_stats(
                current_batch=index,
                total_batches=len(batches),
                pages_processed=pages_processed,
                batches_completed=index,
                eta_seconds=round(eta_seconds, 2),
            )
            self.job_store.update_progress(
                job_id,
                stage=f"generate_{split_name}",
                status="running",
                percent=progress,
                message=(
                    f"Batch {index}/{len(batches)} para {split_name}: "
                    f"{len(batch_pages)} paginas, {len(batch_chunk_ids)} chunks, salida acumulada={total_examples}"
                ),
                stats=session.stats_snapshot(),
            )
            if index < len(batches) and config.generation.batch_pause_seconds > 0:
                self.job_store.update_progress(
                    job_id,
                    stage=f"pause_{split_name}",
                    status="running",
                    percent=progress,
                    message=f"Pausa de {config.generation.batch_pause_seconds:.0f}s antes del siguiente lote",
                    stats=session.stats_snapshot(),
                )
                time.sleep(config.generation.batch_pause_seconds)
            self._check_control(job_id=job_id, stage=f"generate_{split_name}", percent=progress, stats=session.stats_snapshot())
        return total_examples

    def _run_job(
        self,
        job_id: str,
        source_dir: Path,
        generate_eval: bool,
        config: ProjectConfig,
        run_dir: Path,
    ) -> None:
        try:
            paths, _ = _paths_and_config(self.project_dir, run_dir=run_dir, work_subdir=job_id)
            secret_store = self.secret_store
            backend = build_backend(config, store=secret_store)
            session = PipelineSession(
                paths=paths,
                config=config,
                backend=backend,
                control_callback=lambda: self._check_control(
                    job_id=job_id,
                    stage="running",
                    percent=self.job_store.get_job(job_id).percent if self.job_store.get_job(job_id) else 0.0,
                ),
            )

            self.job_store.update_progress(
                job_id,
                stage="scan_folder",
                status="running",
                percent=0.02,
                current_file=str(source_dir),
                message="Scanning folder",
                stats=session.stats_snapshot(),
            )
            self._check_control(job_id=job_id, stage="scan_folder", percent=0.02, stats=session.stats_snapshot())
            document_count, chunk_count = session.ingest(pdf_dir=source_dir, recursive=True)
            self.job_store.update_progress(
                job_id,
                stage="ingest",
                status="running",
                percent=0.18,
                message=f"Ingested {document_count} documents and {chunk_count} chunks",
                stats=session.stats_snapshot(),
            )

            self._check_control(job_id=job_id, stage="ingest", percent=0.18, stats=session.stats_snapshot())
            manifest = session.split()
            self.job_store.update_progress(
                job_id,
                stage="split",
                status="running",
                percent=0.28,
                message=(
                    f"Split frozen in mode {manifest.dataset_mode} with "
                    f"{len(manifest.train_doc_ids)} train docs and {len(manifest.eval_doc_ids)} eval docs"
                ),
                stats=session.stats_snapshot(),
            )
            self._check_control(job_id=job_id, stage="split", percent=0.28, stats=session.stats_snapshot())
            if generate_eval and manifest.dataset_mode == "multi_document" and not manifest.eval_doc_ids:
                raise RuntimeError(
                    "No se pudo construir eval sin leakage por doc_id. Agrega mas PDFs distintos a la carpeta."
                )

            train_total = self._run_batched_generation(
                job_id=job_id,
                session=session,
                paths=paths,
                config=config,
                split_name="train",
                split_doc_ids=manifest.train_doc_ids,
                percent_start=0.32,
                percent_end=0.62,
            )
            self.job_store.update_progress(
                job_id,
                stage="generate_train",
                status="running",
                percent=0.62,
                message=f"Generated {train_total} train examples",
                stats=session.stats_snapshot(),
            )
            self._check_control(job_id=job_id, stage="generate_train", percent=0.62, stats=session.stats_snapshot())
            train_summary = session.curate_split("train")
            self.job_store.update_progress(
                job_id,
                stage="judge_train",
                status="running",
                percent=0.7,
                message=f"Accepted {train_summary.accepted} train examples",
                stats=session.stats_snapshot(),
            )

            if generate_eval and manifest.has_clean_eval:
                eval_total = self._run_batched_generation(
                    job_id=job_id,
                    session=session,
                    paths=paths,
                    config=config,
                    split_name="eval",
                    split_doc_ids=manifest.eval_doc_ids,
                    percent_start=0.74,
                    percent_end=0.86,
                )
                self.job_store.update_progress(
                    job_id,
                    stage="generate_eval",
                    status="running",
                    percent=0.86,
                    message=f"Generated {eval_total} eval examples",
                    stats=session.stats_snapshot(),
                )
                self._check_control(job_id=job_id, stage="generate_eval", percent=0.86, stats=session.stats_snapshot())
                eval_summary = session.curate_split("eval")
                self.job_store.update_progress(
                    job_id,
                    stage="judge_eval",
                    status="running",
                    percent=0.88,
                    message=f"Accepted {eval_summary.accepted} eval examples",
                    stats=session.stats_snapshot(),
                )

            self._check_control(job_id=job_id, stage="judge", percent=0.9, stats=session.stats_snapshot())
            train_count, eval_count, review_count = session.export()
            self.job_store.update_progress(
                job_id,
                stage="export",
                status="running",
                percent=0.95,
                message=f"Exported train={train_count}, eval={eval_count}, review={review_count}",
                stats=session.stats_snapshot(),
            )

            report_path, _ = session.report()
            session._update_stats(eta_seconds=0)
            self.job_store.update_progress(
                job_id,
                stage="done",
                status="completed",
                percent=1.0,
                message=f"Completed successfully. Report: {report_path}",
                stats=session.stats_snapshot(),
            )
        except JobCancelledError:
            pass
        except Exception as exc:
            self.job_store.update_progress(
                job_id,
                stage="failed",
                status="failed",
                percent=1.0,
                message=str(exc),
                error=str(exc),
            )
        finally:
            with self._lock:
                self._threads.pop(job_id, None)
                self._dispatch_next_queued()
