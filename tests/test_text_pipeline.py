from synthetic_ds.chunking import chunk_document
from synthetic_ds.models import DocumentRecord
from synthetic_ds.semantic_chunking import SemanticSection, _split_large_section
from synthetic_ds.text import estimate_tokens, normalize_text


def test_normalize_text_removes_hyphenation_and_extra_whitespace() -> None:
    raw = "Intro Header\ninfor-\n mation   relevante\t\tcon   espacios.\n\nFooter"

    cleaned = normalize_text(raw, repeated_lines={"Intro Header", "Footer"})

    assert cleaned == "information relevante con espacios."


def test_chunk_document_prefers_sections_before_token_windows() -> None:
    document = DocumentRecord(
        doc_id="doc-1",
        source_doc="sample.pdf",
        file_path="/tmp/sample.pdf",
        language="es",
        text="## Intro\nUno dos tres cuatro cinco seis.\n## Resultados\nSiete ocho nueve diez once doce.",
        sections=[
            {
                "heading": "Intro",
                "text": "Uno dos tres cuatro cinco seis.",
                "page_start": 1,
                "page_end": 1,
            },
            {
                "heading": "Resultados",
                "text": "Siete ocho nueve diez once doce.",
                "page_start": 2,
                "page_end": 2,
            },
        ],
        page_text=["Uno dos tres cuatro cinco seis.", "Siete ocho nueve diez once doce."],
        metadata={"title": "sample"},
    )

    chunks = chunk_document(document, target_tokens=8, overlap=2)

    assert [chunk.section_path for chunk in chunks] == [["Intro"], ["Resultados"]]
    assert [chunk.page_range for chunk in chunks] == [(1, 1), (2, 2)]
    assert all(chunk.doc_id == "doc-1" for chunk in chunks)
    assert all(chunk.token_count >= 4 for chunk in chunks)


def test_estimate_tokens_is_stable_for_plain_text() -> None:
    assert estimate_tokens("uno dos tres cuatro") == 4


def test_chunk_document_without_sections_preserves_page_ranges() -> None:
    document = DocumentRecord(
        doc_id="doc-pages",
        source_doc="sample.pdf",
        file_path="/tmp/sample.pdf",
        language="es",
        text="uno dos tres cuatro cinco seis siete ocho nueve diez once doce",
        sections=[],
        page_text=[
            "uno dos tres cuatro",
            "cinco seis siete ocho",
            "nueve diez once doce",
        ],
        metadata={"title": "sample"},
    )

    chunks = chunk_document(document, target_tokens=6, overlap=2)

    assert [chunk.page_range for chunk in chunks] == [(1, 2), (2, 3), (3, 3)]
    assert chunks[0].text == "uno dos tres cuatro cinco seis"


def test_chunk_document_splits_sparse_large_pdf_by_page_limit() -> None:
    document = DocumentRecord(
        doc_id="book-1",
        source_doc="book.pdf",
        file_path="/tmp/book.pdf",
        language="es",
        text="\n\n".join(f"pagina {page}" for page in range(1, 7)),
        sections=[],
        page_text=[f"pagina {page}" for page in range(1, 7)],
        metadata={"page_count": 6},
    )

    chunks = chunk_document(
        document,
        target_tokens=8192,
        overlap=0,
        max_pages_per_chunk=2,
    )

    assert [chunk.page_range for chunk in chunks] == [(1, 2), (3, 4), (5, 6)]
    assert [chunk.text for chunk in chunks] == ["pagina 1\n\npagina 2", "pagina 3\n\npagina 4", "pagina 5\n\npagina 6"]
    assert all(chunk.metadata["split_reason"] == "max_pages_per_chunk" for chunk in chunks)


def test_chunk_document_enforces_minimum_chunk_density_for_large_sparse_pdf() -> None:
    document = DocumentRecord(
        doc_id="sparse-book",
        source_doc="sparse.pdf",
        file_path="/tmp/sparse.pdf",
        language="es",
        text="\n\n".join(f"pagina {page}" for page in range(1, 301)),
        sections=[],
        page_text=[f"pagina {page}" for page in range(1, 301)],
        metadata={"page_count": 300},
    )

    chunks = chunk_document(
        document,
        target_tokens=8192,
        overlap=0,
        max_pages_per_chunk=25,
    )

    assert len(chunks) >= 15
    assert chunks[0].metadata["coverage_ratio"] == 1.0
    assert chunks[0].metadata["expected_min_chunks"] == 15


def test_semantic_split_handles_continuous_text_without_double_newlines() -> None:
    section = SemanticSection(
        heading="Documento",
        level=0,
        text=" ".join(f"oracion {index} con contenido suficiente." for index in range(120)),
        page_start=1,
        page_end=12,
    )

    parts = _split_large_section(section, max_tokens=40)

    assert len(parts) > 1
    assert all(part.total_tokens <= 45 for part in parts)
    assert parts[0].page_start == 1
    assert parts[-1].page_end == 12
