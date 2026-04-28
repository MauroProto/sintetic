from synthetic_ds.models import ChunkRecord, ExampleKind
from synthetic_ds.prompts import build_generation_prompt, build_judge_prompt


def make_chunk() -> ChunkRecord:
    return ChunkRecord(
        chunk_id="chunk-1",
        doc_id="doc-1",
        source_doc="source.pdf",
        section_path=["Resumen"],
        page_range=(2, 3),
        text="La tasa de retencion fue de 87.3 por ciento en el trimestre.",
        token_count=12,
        text_hash="abc123",
        neighbors=["chunk-2"],
        metadata={},
    )


def test_generation_prompt_keeps_static_prefix_and_dynamic_chunk() -> None:
    prompt = build_generation_prompt(
        kind=ExampleKind.EXTRACTIVE,
        chunks=[make_chunk()],
        language="es",
        prompt_version="v1",
        refusal_text="No disponible.",
    )

    assert "expert dataset curator" in prompt.system.lower()
    assert "Spanish" in prompt.system
    assert "FRAGMENT 1" in prompt.user
    assert "87.3" in prompt.user
    assert "v1" not in prompt.system


def test_judge_prompt_includes_example_and_evidence() -> None:
    prompt = build_judge_prompt(
        question="Cual es la tasa de retencion?",
        answer="Fue de 87.3 por ciento.",
        evidence=["La tasa de retencion fue de 87.3 por ciento en el trimestre."],
        language="es",
    )

    assert "groundedness" in prompt.system.lower()
    assert "87.3" in prompt.user
