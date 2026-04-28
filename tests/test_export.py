import json

import pytest

from synthetic_ds.exporter import build_training_record, validate_export_guardrails
from synthetic_ds.models import GeneratedExample, JudgeScore, SplitManifest


def test_build_training_record_emits_chat_messages_and_metadata() -> None:
    example = GeneratedExample(
        example_id="ex-1",
        doc_id="doc-1",
        source_doc="doc.pdf",
        chunk_ids=["chunk-1"],
        page_range=(1, 2),
        question_type="extractive",
        difficulty="medium",
        language="es",
        is_answerable=True,
        question="Cual es la tasa?",
        answer="Fue de 87.3 por ciento.",
        evidence=["La tasa de retencion fue de 87.3 por ciento."],
        reasoning=None,
        supporting_facts=[],
        prompt_version="v1",
        teacher_model="accounts/fireworks/routers/kimi-k2p5-turbo",
        judge_score=JudgeScore(
            relevance=0.9,
            groundedness=0.9,
            format=1.0,
            difficulty=0.4,
            overall=0.88,
            rationale="ok",
        ),
        raw_response={"raw": True},
    )

    record = build_training_record(
        example,
        system_prompt="Responde solo usando el documento.",
        split="train",
    )

    payload = json.loads(record.model_dump_json())

    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][2]["content"] == "Fue de 87.3 por ciento."
    assert payload["metadata"]["quality_score"] == 0.88
    assert payload["metadata"]["split"] == "train"


def test_validate_export_guardrails_requires_non_empty_eval_split() -> None:
    manifest = SplitManifest(train_doc_ids=["doc-1"], eval_doc_ids=[], dataset_mode="multi_document")

    with pytest.raises(RuntimeError, match="eval"):
        validate_export_guardrails(
            train_examples=[object()],
            eval_examples=[],
            manifest=manifest,
            require_eval=True,
        )


def test_validate_export_guardrails_allows_single_document_without_eval() -> None:
    manifest = SplitManifest(train_doc_ids=["doc-1"], eval_doc_ids=[], dataset_mode="single_document")

    validate_export_guardrails(
        train_examples=[object()],
        eval_examples=[],
        manifest=manifest,
        require_eval=True,
    )


def test_validate_export_guardrails_allows_partial_train_export_when_opted_in() -> None:
    manifest = SplitManifest(train_doc_ids=["doc-1"], eval_doc_ids=["doc-2"], dataset_mode="multi_document")

    validate_export_guardrails(
        train_examples=[object()],
        eval_examples=[],
        manifest=manifest,
        require_eval=True,
        allow_partial=True,
    )
