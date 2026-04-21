"""Edición in-place de ejemplos curados + re-export automático.

Cambios soportados:
    * update_fields(example_id, patch) → edita question/answer/evidence/etc
    * accept(example_id) → promueve un rejected a accepted
    * reject(example_id, reason) → mueve un accepted a rejected
    * delete(example_id) → elimina el ejemplo

Tras cualquier mutación se regeneran:
    * ``curated/{split}.jsonl`` (accepted)
    * ``curated/{split}-rejected.jsonl``
    * ``curated/{split}-summary.json``
    * ``{run_dir}/train.jsonl`` y ``eval.jsonl`` (re-export público)
    * ``{run_dir}/review_sample.{jsonl,csv}``

Las ediciones preservan los metadatos del judge; si no hay ``judge_score``
y se promueve manualmente, se marca ``rationale="manual override"`` con un
``overall`` neutro de 0.8 para no romper el schema de `JudgeScore`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from synthetic_ds.app_state import JobRecord
from synthetic_ds.config import ProjectConfig
from synthetic_ds.exporter import build_review_items, build_training_record
from synthetic_ds.models import (
    CuratedSummary,
    GeneratedExample,
    JudgeScore,
    RejectedExample,
    SplitManifest,
    TrainingRecord,
)
from synthetic_ds.obs import get_logger
from synthetic_ds.storage import read_json, read_jsonl, write_csv_rows, write_json, write_jsonl


logger = get_logger("examples_editor")


SYSTEM_PROMPT_ES = (
    "Sos un asistente experto. Responde solo usando la informacion del documento provisto. "
    "Si la respuesta no esta en el documento, deci: 'La informacion necesaria para responder esta pregunta no se encuentra en el documento provisto.'"
)


@dataclass
class EditorPaths:
    work_dir: Path
    run_dir: Path
    curated_dir: Path

    @classmethod
    def for_job(cls, job: JobRecord) -> "EditorPaths":
        run_dir = Path(job.artifacts_dir)
        work_dir = run_dir / ".work" / job.job_id
        return cls(work_dir=work_dir, run_dir=run_dir, curated_dir=work_dir / "curated")

    def accepted_path(self, split: str) -> Path:
        return self.curated_dir / f"{split}.jsonl"

    def rejected_path(self, split: str) -> Path:
        return self.curated_dir / f"{split}-rejected.jsonl"

    def summary_path(self, split: str) -> Path:
        return self.curated_dir / f"{split}-summary.json"


class ExampleNotFound(RuntimeError):
    pass


def _find_example(
    paths: EditorPaths, split: str, example_id: str
) -> tuple[str, GeneratedExample | RejectedExample]:
    accepted_path = paths.accepted_path(split)
    if accepted_path.exists():
        for item in read_jsonl(accepted_path, GeneratedExample):
            if item.example_id == example_id:
                return "accepted", item
    rejected_path = paths.rejected_path(split)
    if rejected_path.exists():
        for item in read_jsonl(rejected_path, RejectedExample):
            if item.example.example_id == example_id:
                return "rejected", item
    raise ExampleNotFound(f"example '{example_id}' not found in split '{split}'")


def _apply_patch(example: GeneratedExample, patch: dict[str, Any]) -> GeneratedExample:
    allowed = {"question", "answer", "evidence", "reasoning", "question_type", "difficulty", "is_answerable"}
    update: dict[str, Any] = {}
    for key, value in patch.items():
        if key not in allowed:
            continue
        update[key] = value
    if not update:
        return example
    update["judge_score"] = example.judge_score  # conservar score original
    return example.model_copy(update=update)


def update_example(
    paths: EditorPaths,
    *,
    split: str,
    example_id: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    bucket, item = _find_example(paths, split, example_id)
    if bucket == "accepted":
        accepted = list(read_jsonl(paths.accepted_path(split), GeneratedExample))
        accepted = [
            _apply_patch(existing, patch) if existing.example_id == example_id else existing
            for existing in accepted
        ]
        write_jsonl(accepted, paths.accepted_path(split))
    else:
        rejected = list(read_jsonl(paths.rejected_path(split), RejectedExample))
        rejected = [
            RejectedExample(example=_apply_patch(entry.example, patch), reason=entry.reason)
            if entry.example.example_id == example_id
            else entry
            for entry in rejected
        ]
        write_jsonl(rejected, paths.rejected_path(split))
    return {"split": split, "example_id": example_id, "bucket": bucket, "patched": True}


def accept_example(paths: EditorPaths, *, split: str, example_id: str) -> dict[str, Any]:
    bucket, item = _find_example(paths, split, example_id)
    if bucket == "accepted":
        return {"split": split, "example_id": example_id, "bucket": "accepted", "changed": False}
    rejected = list(read_jsonl(paths.rejected_path(split), RejectedExample))
    promoted: GeneratedExample | None = None
    remaining: list[RejectedExample] = []
    for entry in rejected:
        if entry.example.example_id == example_id:
            example = entry.example
            if example.judge_score is None:
                example = example.model_copy(
                    update={
                        "judge_score": JudgeScore(
                            relevance=0.8,
                            groundedness=0.8,
                            format=0.8,
                            difficulty=0.5,
                            overall=0.8,
                            rationale="manual override",
                        )
                    }
                )
            promoted = example
            continue
        remaining.append(entry)
    if promoted is None:
        raise ExampleNotFound(example_id)
    write_jsonl(remaining, paths.rejected_path(split))
    accepted = list(read_jsonl(paths.accepted_path(split), GeneratedExample))
    accepted.append(promoted)
    write_jsonl(accepted, paths.accepted_path(split))
    return {"split": split, "example_id": example_id, "bucket": "accepted", "changed": True}


def reject_example(
    paths: EditorPaths, *, split: str, example_id: str, reason: str = "manual_rejection"
) -> dict[str, Any]:
    bucket, item = _find_example(paths, split, example_id)
    if bucket == "rejected":
        return {"split": split, "example_id": example_id, "bucket": "rejected", "changed": False}
    accepted = list(read_jsonl(paths.accepted_path(split), GeneratedExample))
    demoted: GeneratedExample | None = None
    remaining: list[GeneratedExample] = []
    for entry in accepted:
        if entry.example_id == example_id:
            demoted = entry
            continue
        remaining.append(entry)
    if demoted is None:
        raise ExampleNotFound(example_id)
    write_jsonl(remaining, paths.accepted_path(split))
    rejected = list(read_jsonl(paths.rejected_path(split), RejectedExample))
    rejected.append(RejectedExample(example=demoted, reason=reason))
    write_jsonl(rejected, paths.rejected_path(split))
    return {"split": split, "example_id": example_id, "bucket": "rejected", "changed": True}


def delete_example(paths: EditorPaths, *, split: str, example_id: str) -> dict[str, Any]:
    bucket, item = _find_example(paths, split, example_id)
    if bucket == "accepted":
        accepted = [e for e in read_jsonl(paths.accepted_path(split), GeneratedExample) if e.example_id != example_id]
        write_jsonl(accepted, paths.accepted_path(split))
    else:
        rejected = [e for e in read_jsonl(paths.rejected_path(split), RejectedExample) if e.example.example_id != example_id]
        write_jsonl(rejected, paths.rejected_path(split))
    return {"split": split, "example_id": example_id, "deleted": True}


def _load_manifest(paths: EditorPaths) -> SplitManifest | None:
    split_path = paths.work_dir / "split.json"
    if not split_path.exists():
        return None
    payload = read_json(split_path)
    if not payload:
        return None
    try:
        return SplitManifest.model_validate(payload)
    except Exception:
        return None


def _recompute_summary(paths: EditorPaths, split: str) -> dict[str, Any]:
    accepted_count = len(read_jsonl(paths.accepted_path(split), GeneratedExample)) if paths.accepted_path(split).exists() else 0
    rejected_items = read_jsonl(paths.rejected_path(split), RejectedExample) if paths.rejected_path(split).exists() else []
    reasons: dict[str, int] = {}
    for entry in rejected_items:
        reasons[entry.reason] = reasons.get(entry.reason, 0) + 1
    summary = CuratedSummary(
        total_input=accepted_count + len(rejected_items),
        accepted=accepted_count,
        rejected=len(rejected_items),
        rejected_by_reason=reasons,
    )
    write_json(summary.model_dump(mode="json"), paths.summary_path(split))
    return summary.model_dump(mode="json")


def reexport_job(paths: EditorPaths, config: ProjectConfig) -> dict[str, int]:
    """Regenera train.jsonl / eval.jsonl / review_sample tras una edición."""
    totals: dict[str, int] = {}
    review_items: list = []
    for split in ("train", "eval"):
        examples = read_jsonl(paths.accepted_path(split), GeneratedExample) if paths.accepted_path(split).exists() else []
        records: list[TrainingRecord] = []
        for example in examples:
            records.append(build_training_record(example, system_prompt=SYSTEM_PROMPT_ES, split=split))
        output_path = paths.run_dir / f"{split}.jsonl"
        if records:
            write_jsonl(records, output_path)
        elif output_path.exists():
            output_path.unlink()
        totals[split] = len(records)
        if split == "train":
            review_items = build_review_items(
                examples, split=split, sample_size=config.review.sample_size
            )
        _recompute_summary(paths, split)

    review_path = paths.run_dir / "review_sample.jsonl"
    csv_path = paths.run_dir / "review_sample.csv"
    if review_items:
        write_jsonl(review_items, review_path)
        rows = [item.model_dump(mode="json") for item in review_items]
        for row in rows:
            if "page_range" in row and isinstance(row["page_range"], (list, tuple)):
                row["page_range"] = list(row["page_range"])
        write_csv_rows(rows, csv_path)
    else:
        for p in (review_path, csv_path):
            if p.exists():
                p.unlink()
    totals["review"] = len(review_items)
    return totals
