from synthetic_ds.curate import curate_examples
from synthetic_ds.models import ChunkRecord, CuratedDataset, GeneratedExample, JudgeScore


def make_chunk() -> ChunkRecord:
    return ChunkRecord(
        chunk_id="chunk-1",
        doc_id="doc-1",
        source_doc="doc.pdf",
        section_path=["Resumen"],
        page_range=(1, 1),
        text="La tasa de retencion fue de 87.3 por ciento.",
        token_count=9,
        text_hash="hash",
        neighbors=[],
        metadata={},
    )


def make_example(question: str, answer: str, *, is_answerable: bool = True) -> GeneratedExample:
    return GeneratedExample(
        example_id=question.lower().replace(" ", "-"),
        doc_id="doc-1",
        source_doc="doc.pdf",
        chunk_ids=["chunk-1"],
        page_range=(1, 1),
        question_type="extractive" if is_answerable else "unanswerable",
        difficulty="low",
        language="es",
        is_answerable=is_answerable,
        question=question,
        answer=answer,
        evidence=["La tasa de retencion fue de 87.3 por ciento."] if is_answerable else [],
        reasoning=None,
        supporting_facts=[],
        prompt_version="v1",
        teacher_model="accounts/fireworks/routers/kimi-k2p5-turbo",
        judge_score=JudgeScore(
            relevance=0.9,
            groundedness=0.92 if is_answerable else 0.85,
            format=1.0,
            difficulty=0.3,
            overall=0.91,
            rationale="ok",
        ),
        raw_response={"ok": True},
    )


def test_curate_examples_discards_bad_refusals_and_duplicates() -> None:
    valid = make_example("Cual es la tasa?", "Fue de 87.3 por ciento.")
    duplicate = make_example("Cual es la tasa?", "Fue de 87.3 por ciento.")
    bad_refusal = make_example(
        "Cuantos empleados hay en Asia?",
        "No se.",
        is_answerable=False,
    )

    curated = curate_examples(
        [valid, duplicate, bad_refusal],
        refusal_text="La informacion necesaria para responder esta pregunta no se encuentra en el documento provisto.",
        groundedness_threshold=0.7,
        overall_threshold=0.7,
    )

    assert isinstance(curated, CuratedDataset)
    assert [item.example_id for item in curated.accepted] == [valid.example_id]
    assert curated.summary.rejected_by_reason["duplicate"] == 1
    assert curated.summary.rejected_by_reason["invalid_refusal"] == 1


def test_curate_examples_requires_evidence_for_answerable_items() -> None:
    invalid = make_example("Cual es la tasa?", "Fue de 87.3 por ciento.")
    invalid.evidence = []

    curated = curate_examples(
        [invalid],
        refusal_text="La informacion necesaria para responder esta pregunta no se encuentra en el documento provisto.",
        groundedness_threshold=0.7,
        overall_threshold=0.7,
    )

    assert curated.accepted == []
    assert curated.summary.rejected_by_reason["missing_evidence"] == 1
