from synthetic_ds.generate import select_pending_chunks
from synthetic_ds.models import ChunkRecord, GeneratedExample


def make_chunk(chunk_id: str) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id,
        doc_id="doc-1",
        source_doc="doc.pdf",
        section_path=[],
        page_range=(1, 1),
        text="contenido",
        token_count=1,
        text_hash=chunk_id,
        neighbors=[],
        metadata={},
    )


def make_example(chunk_id: str) -> GeneratedExample:
    return GeneratedExample(
        example_id=f"ex-{chunk_id}",
        doc_id="doc-1",
        source_doc="doc.pdf",
        chunk_ids=[chunk_id],
        page_range=(1, 1),
        question_type="extractive",
        difficulty="low",
        language="es",
        is_answerable=True,
        question="q",
        answer="a",
        evidence=["e"],
        prompt_version="v1",
        teacher_model="model",
        raw_response={},
    )


def test_select_pending_chunks_skips_already_generated_primary_chunks() -> None:
    chunks = [make_chunk("c1"), make_chunk("c2"), make_chunk("c3")]
    existing = [make_example("c2")]

    pending = select_pending_chunks(chunks, existing)

    assert [chunk.chunk_id for chunk in pending] == ["c1", "c3"]
