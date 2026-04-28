from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from synthetic_ds.curate import curate_examples
from synthetic_ds.exporter import build_review_items, build_training_record, validate_export_guardrails
from synthetic_ds.generate import (
    generate_document_summary,
    generate_example_for_target,
    judge_example,
    plan_generation_targets,
    normalize_question_type,
    select_pending_targets,
)
from synthetic_ds.ingest import ingest_directory
from synthetic_ds.models import (
    ChunkRecord,
    CuratedSummary,
    DocumentRecord,
    GeneratedExample,
    ProjectPaths,
    SplitManifest,
)
from synthetic_ds.reporting import build_report_markdown
from synthetic_ds.splitter import split_documents
from synthetic_ds.storage import (
    PHASES,
    append_jsonl,
    detect_completed_phases,
    read_json,
    read_jsonl,
    save_phase_checkpoint,
    write_csv_rows,
    write_json,
    write_jsonl,
)


class JobCancelledError(RuntimeError):
    pass


class PipelineSession:
    def __init__(
        self,
        *,
        paths: ProjectPaths,
        config,
        backend=None,
        control_callback: Callable[[], None] | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.paths = paths
        self.config = config
        self.backend = backend
        self.control_callback = control_callback
        self.progress_callback = progress_callback
        self.progress_path = self.paths.artifacts_dir / "progress.json"
        self.metrics_path = self.paths.artifacts_dir / "metrics.json"
        self.judged_dir = self.paths.artifacts_dir / "judged"
        self.judged_dir.mkdir(parents=True, exist_ok=True)
        self._stats = self._load_progress()

    def completed_phases(self) -> list[str]:
        return detect_completed_phases(self.paths.artifacts_dir)

    def save_checkpoint(self, phase: str, *, output_files: Iterable[Path | str] = (), stats: dict | None = None) -> None:
        save_phase_checkpoint(
            self.paths.artifacts_dir,
            phase,
            output_files=output_files,
            stats=stats or self.stats_snapshot(),
        )

    def _load_progress(self) -> dict[str, Any]:
        payload = read_json(self.progress_path)
        if payload:
            return payload
        return {
            "document_count": 0,
            "chunk_count": 0,
            "total_pages": 0,
            "pages_processed": 0,
            "batches_completed": 0,
            "requests_completed": 0,
            "generated": {"train": 0, "eval": 0},
            "judged": {"train": 0, "eval": 0},
            "accepted": {"train": 0, "eval": 0},
            "rejected": {"train": 0, "eval": 0},
            "current_split": None,
            "current_batch": 0,
            "total_batches": 0,
            "eta_seconds": None,
            "dataset_mode": None,
            "clean_eval": False,
            "updated_at": time.time(),
        }

    def stats_snapshot(self) -> dict[str, Any]:
        return dict(self._stats)

    def _persist_progress(self) -> None:
        self._stats["updated_at"] = time.time()
        write_json(self._stats, self.progress_path)
        write_json(self._stats, self.metrics_path)
        if self.progress_callback:
            self.progress_callback(self.stats_snapshot())

    def _update_stats(self, **updates: Any) -> None:
        for key, value in updates.items():
            self._stats[key] = value
        self._persist_progress()

    def _touch_control(self) -> None:
        if self.control_callback:
            self.control_callback()

    def ingest(self, *, pdf_dir: Path, recursive: bool = True, max_documents: int | None = None) -> tuple[int, int]:
        if self.paths.documents_path.exists() and self.paths.chunks_path.exists():
            documents = read_jsonl(self.paths.documents_path, DocumentRecord)
            chunks = read_jsonl(self.paths.chunks_path, ChunkRecord)
            self._update_stats(
                document_count=len(documents),
                chunk_count=len(chunks),
                total_pages=sum(int(doc.metadata.get("page_count", 0)) for doc in documents),
            )
            self.save_checkpoint(
                "ingest",
                output_files=[self.paths.documents_path, self.paths.chunks_path],
                stats={"documents": len(documents), "chunks": len(chunks)},
            )
            return len(documents), len(chunks)

        result = ingest_directory(
            pdf_dir=pdf_dir.resolve(),
            primary_parser=self.config.parsing.primary_parser,
            fallback_parser=self.config.parsing.fallback_parser,
            target_tokens=self.config.chunking.target_tokens,
            overlap=self.config.chunking.overlap,
            default_language=self.config.parsing.default_language,
            chunking_strategy=self.config.chunking.strategy,
            recursive=recursive,
            page_asset_dir=self.paths.artifacts_dir / "pages",
            enable_ocr=self.config.parsing.enable_ocr,
            ocr_text_min_chars=self.config.parsing.ocr_text_min_chars,
            render_page_images=self.config.parsing.render_page_images,
            page_image_dpi=self.config.parsing.page_image_dpi,
            max_pages_per_chunk=self.config.chunking.max_pages_per_chunk,
            max_documents=max_documents,
            docling_max_pages=self.config.parsing.docling_max_pages,
            docling_max_ram_mb=self.config.parsing.docling_max_ram_mb,
        )
        write_jsonl(result.documents, self.paths.documents_path)
        write_jsonl(result.chunks, self.paths.chunks_path)
        self._update_stats(
            document_count=len(result.documents),
            chunk_count=len(result.chunks),
            total_pages=sum(int(doc.metadata.get("page_count", 0)) for doc in result.documents),
        )
        self.save_checkpoint(
            "ingest",
            output_files=[self.paths.documents_path, self.paths.chunks_path],
            stats={"documents": len(result.documents), "chunks": len(result.chunks)},
        )
        return len(result.documents), len(result.chunks)

    def split(self) -> SplitManifest:
        payload = read_json(self.paths.split_path)
        if payload:
            manifest = SplitManifest.model_validate(payload)
            self._update_stats(dataset_mode=manifest.dataset_mode, clean_eval=manifest.has_clean_eval)
            self.save_checkpoint(
                "split",
                output_files=[self.paths.split_path],
                stats={
                    "train_docs": len(manifest.train_doc_ids),
                    "eval_docs": len(manifest.eval_doc_ids),
                    "dataset_mode": str(manifest.dataset_mode),
                },
            )
            return manifest
        documents = read_jsonl(self.paths.documents_path, DocumentRecord)
        manifest = split_documents(documents)
        write_json(manifest.model_dump(mode="json"), self.paths.split_path)
        self._update_stats(dataset_mode=manifest.dataset_mode, clean_eval=manifest.has_clean_eval)
        self.save_checkpoint(
            "split",
            output_files=[self.paths.split_path],
            stats={
                "train_docs": len(manifest.train_doc_ids),
                "eval_docs": len(manifest.eval_doc_ids),
                "dataset_mode": str(manifest.dataset_mode),
            },
        )
        return manifest

    def _select_chunks(
        self,
        *,
        split_name: str,
        doc_ids: list[str] | None = None,
        chunk_ids: list[str] | None = None,
    ) -> list[ChunkRecord]:
        chunks = read_jsonl(self.paths.chunks_path, ChunkRecord)
        manifest = SplitManifest.model_validate(read_json(self.paths.split_path))
        selected_doc_ids = set(manifest.train_doc_ids if split_name == "train" else manifest.eval_doc_ids)
        if doc_ids is not None:
            selected_doc_ids &= set(doc_ids)
        selected_chunks = [chunk for chunk in chunks if chunk.doc_id in selected_doc_ids]
        if chunk_ids is not None:
            allowed_chunk_ids = set(chunk_ids)
            selected_chunks = [chunk for chunk in selected_chunks if chunk.chunk_id in allowed_chunk_ids]
        return selected_chunks

    async def _run_tasks(
        self,
        *,
        items: Iterable[Any],
        worker_count: int,
        task_factory: Callable[[Any], Any],
        on_result: Callable[[Any], None],
    ) -> int:
        semaphore = asyncio.Semaphore(max(1, worker_count))

        async def runner(item: Any):
            async with semaphore:
                self._touch_control()
                return await asyncio.to_thread(task_factory, item)

        tasks = [asyncio.create_task(runner(item)) for item in items]
        completed = 0
        for future in asyncio.as_completed(tasks):
            result = await future
            on_result(result)
            completed += 1
            self._touch_control()
        return completed

    def generate_split(
        self,
        split_name: str,
        *,
        doc_ids: list[str] | None = None,
        chunk_ids: list[str] | None = None,
    ) -> int:
        if self.backend is None:
            raise RuntimeError("PipelineSession requires a backend for generation")

        generated_path = self.paths.generated_dir / f"{split_name}.jsonl"
        selected_chunks = self._select_chunks(split_name=split_name, doc_ids=doc_ids, chunk_ids=chunk_ids)
        existing = read_jsonl(generated_path, GeneratedExample)
        targets = plan_generation_targets(
            selected_chunks,
            self.config.generation.mix,
            targets_per_chunk=max(1, getattr(self.config.generation, "targets_per_chunk", 1)),
        )
        pending_targets = select_pending_targets(targets, existing)
        if not pending_targets:
            if not generated_path.exists():
                write_jsonl(existing, generated_path)
            self.save_checkpoint(
                f"generate_{split_name}",
                output_files=[generated_path],
                stats={"examples_generated": len(existing)},
            )
            return len(existing)

        chunk_map = {chunk.chunk_id: chunk for chunk in selected_chunks}
        generation_workers, _judge_workers = self.config.generation.resolved_worker_settings()
        start_count = len(existing)
        self._stats["current_split"] = split_name
        
        # Generar resumen del documento para contexto
        doc_summary = generate_document_summary(
            selected_chunks, 
            self.backend, 
            self.config.parsing.default_language
        )
        
        # Para UNANSWERABLE, preparar texto completo del documento
        all_chunks_text = "\n\n".join(chunk.text for chunk in selected_chunks)

        def build_item(target) -> GeneratedExample:
            return generate_example_for_target(
                target=target,
                chunk_map=chunk_map,
                backend=self.backend,
                mix=self.config.generation.mix,
                prompt_version=self.config.generation.prompt_version,
                language=self.config.parsing.default_language,
                session_id=f"{split_name}-generate",
                teacher_model=self.config.providers.profile_for().model,
                refusal_text=self.config.generation.refusal_text,
                max_attempts=self.config.generation.max_generation_attempts_per_target,
                max_pages_per_chunk=self.config.parsing.multimodal_max_pages_per_chunk,
                doc_summary=doc_summary,
                all_chunks_text=all_chunks_text,
            )

        def on_result(example: GeneratedExample) -> None:
            append_jsonl(example, generated_path)
            self._stats["requests_completed"] += 1
            self._stats["generated"][split_name] = self._stats["generated"].get(split_name, start_count) + 1
            self._persist_progress()

        asyncio.run(
            self._run_tasks(
                items=pending_targets,
                worker_count=generation_workers,
                task_factory=build_item,
                on_result=on_result,
            )
        )
        total_generated = len(read_jsonl(generated_path, GeneratedExample))
        self.save_checkpoint(
            f"generate_{split_name}",
            output_files=[generated_path],
            stats={"examples_generated": total_generated},
        )
        return total_generated

    def curate_split(self, split_name: str) -> CuratedSummary:
        if self.backend is None:
            raise RuntimeError("PipelineSession requires a backend for judging")

        generated_path = self.paths.generated_dir / f"{split_name}.jsonl"
        generated = read_jsonl(generated_path, GeneratedExample)
        if not generated:
            summary = CuratedSummary(total_input=0, accepted=0, rejected=0, rejected_by_reason={})
            write_jsonl([], self.paths.curated_dir / f"{split_name}.jsonl")
            write_jsonl([], self.paths.curated_dir / f"{split_name}-rejected.jsonl")
            write_json(summary.model_dump(mode="json"), self.paths.curated_dir / f"{split_name}-summary.json")
            self.save_checkpoint(
                f"judge_{split_name}",
                output_files=[
                    self.paths.curated_dir / f"{split_name}.jsonl",
                    self.paths.curated_dir / f"{split_name}-summary.json",
                ],
                stats=summary.model_dump(mode="json"),
            )
            return summary

        judged_path = self.judged_dir / f"{split_name}.jsonl"
        existing_judged = read_jsonl(judged_path, GeneratedExample)
        judged_map = {example.example_id: example for example in existing_judged}

        for example in generated:
            if example.judge_score and example.example_id not in judged_map:
                append_jsonl(example, judged_path)
                judged_map[example.example_id] = example

        pending = [example for example in generated if example.example_id not in judged_map]
        _generation_workers, judge_workers = self.config.generation.resolved_worker_settings()
        self._stats["current_split"] = split_name

        # Reutilizar el resumen del documento para el juez
        doc_summary = generate_document_summary(
            read_jsonl(self.paths.chunks_path, ChunkRecord),
            self.backend,
            self.config.parsing.default_language
        )
        
        def judge(item: GeneratedExample) -> GeneratedExample:
            return judge_example(
                example=item, 
                backend=self.backend, 
                session_id=f"{split_name}-judge",
                doc_summary=doc_summary
            )

        def on_result(example: GeneratedExample) -> None:
            append_jsonl(example, judged_path)
            judged_map[example.example_id] = example
            self._stats["requests_completed"] += 1
            self._stats["judged"][split_name] = self._stats["judged"].get(split_name, 0) + 1
            self._persist_progress()

        if pending:
            asyncio.run(
                self._run_tasks(
                    items=pending,
                    worker_count=judge_workers,
                    task_factory=judge,
                    on_result=on_result,
                )
            )

        ordered_judged = [judged_map[example.example_id] for example in generated if example.example_id in judged_map]
        curated = curate_examples(
            ordered_judged,
            refusal_text=self.config.generation.refusal_text,
            groundedness_threshold=self.config.filters.effective_groundedness,
            overall_threshold=self.config.filters.effective_overall,
        )
        write_jsonl(curated.accepted, self.paths.curated_dir / f"{split_name}.jsonl")
        write_jsonl(curated.rejected, self.paths.curated_dir / f"{split_name}-rejected.jsonl")
        write_json(curated.summary.model_dump(mode="json"), self.paths.curated_dir / f"{split_name}-summary.json")
        self._stats["accepted"][split_name] = curated.summary.accepted
        self._stats["rejected"][split_name] = curated.summary.rejected
        self._persist_progress()
        self.save_checkpoint(
            f"judge_{split_name}",
            output_files=[
                judged_path,
                self.paths.curated_dir / f"{split_name}.jsonl",
                self.paths.curated_dir / f"{split_name}-summary.json",
            ],
            stats=curated.summary.model_dump(mode="json"),
        )
        return curated.summary

    def export(self) -> tuple[int, int, int]:
        train = read_jsonl(self.paths.curated_dir / "train.jsonl", GeneratedExample)
        eval_items = read_jsonl(self.paths.curated_dir / "eval.jsonl", GeneratedExample)
        manifest = SplitManifest.model_validate(read_json(self.paths.split_path))
        validate_export_guardrails(
            train_examples=train,
            eval_examples=eval_items,
            manifest=manifest,
            require_eval=self.config.export.require_eval_split,
            allow_partial=self.config.export.allow_partial_export,
        )
        system_prompt = (
            "Sos un asistente experto. Responde solo usando la informacion del documento provisto. "
            f"Si la respuesta no esta en el documento, deci: '{self.config.generation.refusal_text}'"
        )
        train_records = [build_training_record(item, system_prompt=system_prompt, split="train") for item in train]
        write_jsonl(train_records, self.paths.exports_dir / "train.jsonl")
        if manifest.has_clean_eval:
            eval_records = [build_training_record(item, system_prompt=system_prompt, split="eval") for item in eval_items]
            write_jsonl(eval_records, self.paths.exports_dir / "eval.jsonl")
        else:
            eval_records = []
            eval_path = self.paths.exports_dir / "eval.jsonl"
            if eval_path.exists():
                eval_path.unlink()

        review_items = build_review_items(train, split="train", sample_size=self.config.review.sample_size)
        if manifest.has_clean_eval and len(review_items) < self.config.review.sample_size:
            remainder = self.config.review.sample_size - len(review_items)
            review_items.extend(build_review_items(eval_items, split="eval", sample_size=remainder))
        write_jsonl(review_items, self.paths.exports_dir / "review_sample.jsonl")
        write_csv_rows([item.model_dump(mode="json") for item in review_items], self.paths.exports_dir / "review_sample.csv")
        self.save_checkpoint(
            "export",
            output_files=[
                self.paths.exports_dir / "train.jsonl",
                self.paths.exports_dir / "eval.jsonl",
                self.paths.exports_dir / "review_sample.jsonl",
                self.paths.exports_dir / "review_sample.csv",
            ],
            stats={"train": len(train_records), "eval": len(eval_records), "review": len(review_items)},
        )
        return len(train_records), len(eval_records), len(review_items)

    def report(self) -> tuple[Path, str]:
        documents = read_jsonl(self.paths.documents_path, DocumentRecord)
        chunks = read_jsonl(self.paths.chunks_path, ChunkRecord)
        manifest = SplitManifest.model_validate(read_json(self.paths.split_path))
        generated_counts = {
            split_name: len(read_jsonl(self.paths.generated_dir / f"{split_name}.jsonl", GeneratedExample))
            for split_name in ("train", "eval")
        }
        curated_summaries: dict[str, CuratedSummary] = {}
        for split_name in ("train", "eval"):
            summary_payload = read_json(self.paths.curated_dir / f"{split_name}-summary.json")
            if summary_payload:
                curated_summaries[split_name] = CuratedSummary.model_validate(summary_payload)
        markdown = build_report_markdown(
            document_count=len(documents),
            chunk_count=len(chunks),
            generated_counts=generated_counts,
            curated_summaries=curated_summaries,
            manifest=manifest,
        )
        report_path = self.paths.reports_dir / "latest.md"
        report_path.write_text(markdown, encoding="utf-8")
        self.save_checkpoint("report", output_files=[report_path], stats={"report": str(report_path)})
        return report_path, markdown
