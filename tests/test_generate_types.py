from synthetic_ds.generate import generate_example_for_target, normalize_question_type
from synthetic_ds.models import ChunkRecord, ExampleKind, GenerationTarget


def test_normalize_question_type_maps_common_variants_to_canonical_labels() -> None:
    assert normalize_question_type("fact") == "extractive"
    assert normalize_question_type("factoid") == "extractive"
    assert normalize_question_type("literal") == "extractive"
    assert normalize_question_type("factual") == "extractive"
    assert normalize_question_type("multi-hop") == "multi_chunk"
    assert normalize_question_type("unknown") == "unknown"


class PlaceholderEvidenceBackend:
    def generate_structured(self, *, system_prompt: str, user_prompt: str, json_schema: dict, session_id: str) -> dict:
        return {
            "question": "¿Cuál es el criterio de éxito?",
            "answer": "La retencion global debe superar 88 por ciento.",
            "evidence": ["FRAGMENTO 1"],
            "reasoning": None,
            "supporting_facts": [],
            "question_type": "extractive",
            "difficulty": "easy",
            "is_answerable": True,
        }


def test_generate_example_for_target_replaces_placeholder_evidence_with_chunk_text() -> None:
    chunk = ChunkRecord(
        chunk_id="chunk-1",
        doc_id="doc-1",
        source_doc="doc.pdf",
        section_path=[],
        page_range=(1, 1),
        text="Criterios de exito. La retencion global debe superar 88 por ciento.",
        token_count=10,
        text_hash="hash-1",
        neighbors=[],
        metadata={},
    )
    example = generate_example_for_target(
        target=GenerationTarget(primary_chunk_id="chunk-1", requested_kind=ExampleKind.EXTRACTIVE),
        chunk_map={"chunk-1": chunk},
        backend=PlaceholderEvidenceBackend(),
        mix={},
        prompt_version="v1",
        language="es",
        session_id="test",
        teacher_model="teacher",
        refusal_text="No disponible.",
        max_attempts=1,
        max_pages_per_chunk=1,
    )

    assert example.evidence
    assert example.evidence[0] != "FRAGMENTO 1"
    assert "retencion global" in example.evidence[0].lower()
