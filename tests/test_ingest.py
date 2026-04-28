from pathlib import Path

import fitz

from synthetic_ds.models import DocumentRecord
from synthetic_ds.ingest import ingest_directory, parse_pdf


def test_ingest_directory_parses_pdf_and_builds_chunks(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    pdf_path = pdf_dir / "sample.pdf"

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Introduccion\nLa tasa de retencion fue de 87.3 por ciento.\nResultados\nLa mejora fue de 2.1 puntos.")
    doc.save(pdf_path)
    doc.close()

    result = ingest_directory(
        pdf_dir=pdf_dir,
        primary_parser="pymupdf",
        fallback_parser="pymupdf",
        target_tokens=12,
        overlap=2,
        default_language="es",
    )

    assert len(result.documents) == 1
    assert len(result.chunks) >= 1
    assert result.documents[0].source_doc == "sample.pdf"
    assert result.chunks[0].doc_id == result.documents[0].doc_id


def test_ingest_directory_renders_page_images_for_visual_pages(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    pdf_path = pdf_dir / "visual.pdf"

    doc = fitz.open()
    page = doc.new_page()
    page.draw_rect(fitz.Rect(72, 72, 240, 180), color=(0, 0, 0), fill=(0.9, 0.9, 0.9))
    page.insert_text((72, 220), "Formula E = mc^2")
    doc.save(pdf_path)
    doc.close()

    result = ingest_directory(
        pdf_dir=pdf_dir,
        primary_parser="pymupdf",
        fallback_parser="pymupdf",
        target_tokens=50,
        overlap=5,
        default_language="es",
        page_asset_dir=tmp_path / "page-assets",
        enable_ocr=False,
        render_page_images=True,
    )

    assert len(result.documents) == 1
    document = result.documents[0]
    chunk = result.chunks[0]

    assert document.metadata["page_count"] == 1
    assert document.metadata["multimodal_pages"] == 1
    assert chunk.metadata["requires_multimodal"] is True
    assert chunk.metadata["page_image_paths"]
    assert Path(chunk.metadata["page_image_paths"][0]).exists()


def test_ingest_directory_respects_configured_chunking_strategy(tmp_path: Path, monkeypatch) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    pdf_path = pdf_dir / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    document = DocumentRecord(
        doc_id="doc-1",
        source_doc="sample.pdf",
        file_path=str(pdf_path),
        language="es",
        text="uno dos tres cuatro cinco seis",
        sections=[],
        page_text=["uno dos tres cuatro cinco seis"],
        metadata={"page_count": 1},
    )

    seen: dict[str, object] = {}

    monkeypatch.setattr("synthetic_ds.ingest.discover_pdf_paths", lambda *_args, **_kwargs: [pdf_path])
    monkeypatch.setattr("synthetic_ds.ingest.parse_pdf", lambda *_args, **_kwargs: document)

    def fake_chunk_document(
        record: DocumentRecord,
        target_tokens: int = 8192,
        overlap: int = 200,
        *,
        strategy: str | None = None,
        use_semantic: bool | None = None,
        max_pages_per_chunk: int | None = None,
    ) -> list[object]:
        seen["doc_id"] = record.doc_id
        seen["target_tokens"] = target_tokens
        seen["overlap"] = overlap
        seen["strategy"] = strategy
        seen["use_semantic"] = use_semantic
        seen["max_pages_per_chunk"] = max_pages_per_chunk
        return []

    monkeypatch.setattr("synthetic_ds.ingest.chunk_document", fake_chunk_document)

    ingest_directory(
        pdf_dir=pdf_dir,
        primary_parser="pymupdf",
        fallback_parser="pymupdf",
        target_tokens=12,
        overlap=2,
        default_language="es",
        chunking_strategy="headings_first",
    )

    assert seen == {
        "doc_id": "doc-1",
        "target_tokens": 12,
        "overlap": 2,
        "strategy": "headings_first",
        "use_semantic": None,
        "max_pages_per_chunk": None,
    }


def test_ingest_directory_passes_page_limit_to_chunker(tmp_path: Path, monkeypatch) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    pdf_path = pdf_dir / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    document = DocumentRecord(
        doc_id="doc-1",
        source_doc="sample.pdf",
        file_path=str(pdf_path),
        language="es",
        text="uno dos tres",
        sections=[],
        page_text=["uno", "dos", "tres"],
        metadata={"page_count": 3},
    )

    seen: dict[str, object] = {}

    monkeypatch.setattr("synthetic_ds.ingest.discover_pdf_paths", lambda *_args, **_kwargs: [pdf_path])
    monkeypatch.setattr("synthetic_ds.ingest.parse_pdf", lambda *_args, **_kwargs: document)

    def fake_chunk_document(
        record: DocumentRecord,
        target_tokens: int = 8192,
        overlap: int = 200,
        *,
        strategy: str | None = None,
        use_semantic: bool | None = None,
        max_pages_per_chunk: int | None = None,
    ) -> list[object]:
        seen["doc_id"] = record.doc_id
        seen["max_pages_per_chunk"] = max_pages_per_chunk
        return []

    monkeypatch.setattr("synthetic_ds.ingest.chunk_document", fake_chunk_document)

    ingest_directory(
        pdf_dir=pdf_dir,
        primary_parser="pymupdf",
        fallback_parser="pymupdf",
        target_tokens=12,
        overlap=2,
        default_language="es",
        max_pages_per_chunk=2,
    )

    assert seen == {"doc_id": "doc-1", "max_pages_per_chunk": 2}


def test_ingest_directory_can_limit_number_of_documents(tmp_path: Path, monkeypatch) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    pdf_paths = [pdf_dir / f"book-{index}.pdf" for index in range(1, 4)]
    for path in pdf_paths:
        path.write_bytes(b"%PDF-1.4")

    parsed: list[str] = []

    def fake_parse_pdf(path: Path, *_args, **_kwargs) -> DocumentRecord:
        parsed.append(path.name)
        return DocumentRecord(
            doc_id=path.stem,
            source_doc=path.name,
            file_path=str(path),
            language="es",
            text="contenido",
            sections=[],
            page_text=["contenido"],
            metadata={"page_count": 1},
        )

    monkeypatch.setattr("synthetic_ds.ingest.discover_pdf_paths", lambda *_args, **_kwargs: pdf_paths)
    monkeypatch.setattr("synthetic_ds.ingest.parse_pdf", fake_parse_pdf)
    monkeypatch.setattr("synthetic_ds.ingest.chunk_document", lambda *_args, **_kwargs: [])

    result = ingest_directory(
        pdf_dir=pdf_dir,
        primary_parser="pymupdf",
        fallback_parser="pymupdf",
        target_tokens=12,
        overlap=2,
        default_language="es",
        max_documents=2,
    )

    assert parsed == ["book-1.pdf", "book-2.pdf"]
    assert [document.source_doc for document in result.documents] == ["book-1.pdf", "book-2.pdf"]


def test_parse_pdf_skips_docling_when_pdf_exceeds_page_limit(tmp_path: Path) -> None:
    pdf_path = tmp_path / "large.pdf"
    doc = fitz.open()
    for index in range(3):
        page = doc.new_page()
        page.insert_text((72, 72), f"Pagina {index + 1}")
    doc.save(pdf_path)
    doc.close()

    record = parse_pdf(
        pdf_path,
        primary_parser="docling",
        fallback_parser="pymupdf",
        default_language="es",
        enable_ocr=False,
        render_page_images=False,
        docling_max_pages=2,
    )

    assert record.metadata["parser"] == "pymupdf"
    assert record.metadata["parser_skip_reason"] == "docling_max_pages"
