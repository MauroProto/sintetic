from __future__ import annotations

from synthetic_ds.generate import normalize_question_type
from synthetic_ds.models import GeneratedExample, ReviewItem, SplitManifest, TrainingRecord


def build_training_record(example: GeneratedExample, *, system_prompt: str, split: str) -> TrainingRecord:
    quality_score = example.judge_score.overall if example.judge_score else 0.0
    return TrainingRecord(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": example.question},
            {"role": "assistant", "content": example.answer},
        ],
        metadata={
            "example_id": example.example_id,
            "source_doc": example.source_doc,
            "doc_id": example.doc_id,
            "chunk_ids": example.chunk_ids,
            "page_range": list(example.page_range),
            "question_type": normalize_question_type(example.question_type),
            "difficulty": example.difficulty,
            "is_answerable": example.is_answerable,
            "teacher_model": example.teacher_model,
            "judge_model": example.teacher_model,
            "quality_score": quality_score,
            "split": split,
            "prompt_version": example.prompt_version,
            "language": example.language,
        },
    )


def build_review_items(examples: list[GeneratedExample], *, split: str, sample_size: int) -> list[ReviewItem]:
    ordered = sorted(
        examples,
        key=lambda item: (
            item.question_type,
            item.judge_score.overall if item.judge_score else 0.0,
            item.example_id,
        ),
    )
    selected = ordered[: max(1, min(sample_size, len(ordered)))] if ordered else []
    return [
        ReviewItem(
            example_id=item.example_id,
            split=split,
            question_type=normalize_question_type(item.question_type),
            quality_score=item.judge_score.overall if item.judge_score else 0.0,
            question=item.question,
            answer=item.answer,
            source_doc=item.source_doc,
            page_range=item.page_range,
        )
        for item in selected
    ]


def validate_export_guardrails(
    *,
    train_examples: list[GeneratedExample] | list[object],
    eval_examples: list[GeneratedExample] | list[object],
    manifest: SplitManifest,
    require_eval: bool,
) -> None:
    if not train_examples:
        raise RuntimeError("No hay ejemplos de train curados para exportar.")
    if manifest.dataset_mode == "single_document":
        return
    if require_eval and (not manifest.eval_doc_ids or not eval_examples):
        raise RuntimeError("No se puede exportar sin un eval no vacio. Agrega mas PDFs o habilita generate_eval.")
