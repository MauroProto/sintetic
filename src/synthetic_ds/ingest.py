from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

import fitz

import logging

from synthetic_ds.chunking import chunk_document
from synthetic_ds.indexing import attach_neighbors
from synthetic_ds.math_markers import mark_math
from synthetic_ds.models import DocumentRecord, DocumentSection, IngestResult
from synthetic_ds.obs import get_logger, log_event
from synthetic_ds.text import detect_language, normalize_text


logger = get_logger("ingest")
_OCR_WARNING_EMITTED = False


def _doc_id_from_path(path: Path) -> str:
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:10]
    return f"{path.stem.lower().replace(' ', '-')}-{digest}"


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    words = stripped.split()
    if len(words) > 8:
        return False
    return stripped.istitle() or stripped.isupper() or stripped.startswith("#")


def _sections_from_pages(page_text: list[str]) -> list[DocumentSection]:
    sections: list[DocumentSection] = []
    current_heading = "Documento"
    current_lines: list[str] = []
    section_start = 1

    def flush(page_index: int) -> None:
        nonlocal current_lines, section_start, current_heading
        cleaned = normalize_text("\n".join(current_lines))
        if cleaned:
            sections.append(
                DocumentSection(
                    heading=current_heading,
                    text=cleaned,
                    page_start=section_start,
                    page_end=page_index,
                )
            )
        current_lines = []

    for page_number, page in enumerate(page_text, start=1):
        for raw_line in page.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if _looks_like_heading(line):
                flush(page_number)
                current_heading = line.lstrip("# ").strip()
                section_start = page_number
                continue
            current_lines.append(line)

    flush(len(page_text) or 1)
    return sections


def _page_has_visual_content(page: fitz.Page, raw_text: str) -> bool:
    formula_markers = ("=", "≈", "≤", "≥", "±", "√", "∑", "∫", "^", "->", "→")
    try:
        has_images = bool(page.get_images(full=True))
    except Exception:  # pragma: no cover - defensive
        has_images = False
    try:
        has_drawings = bool(page.get_drawings())
    except Exception:  # pragma: no cover - defensive
        has_drawings = False
    formula_like = any(marker in raw_text for marker in formula_markers)
    return has_images or has_drawings or formula_like


def _render_page_image(
    page: fitz.Page,
    *,
    page_asset_dir: Path,
    doc_id: str,
    page_number: int,
    dpi: int,
) -> Path:
    target_dir = page_asset_dir / doc_id
    target_dir.mkdir(parents=True, exist_ok=True)
    scale = max(1.0, dpi / 72.0)
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    image_path = target_dir / f"page-{page_number:04d}.png"
    pixmap.save(image_path)
    return image_path


def _ocr_page_text(page: fitz.Page) -> str:
    global _OCR_WARNING_EMITTED
    if shutil.which("tesseract") is None:
        if not _OCR_WARNING_EMITTED:
            log_event(
                logger,
                logging.WARNING,
                "ocr_unavailable_tesseract_missing",
                hint="brew install tesseract tesseract-lang (macOS) or apt install tesseract-ocr tesseract-ocr-all (Linux)",
            )
            _OCR_WARNING_EMITTED = True
        return ""
    try:
        text_page = page.get_textpage_ocr()
        return page.get_text("text", textpage=text_page)
    except Exception as exc:
        log_event(logger, logging.WARNING, "ocr_page_failed", exc=str(exc)[:200])
        return ""


def _pdf_page_count(path: Path) -> int | None:
    try:
        with fitz.open(path) as doc:
            return doc.page_count
    except Exception:
        return None


def _available_ram_mb() -> int | None:
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        for line in meminfo.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("MemAvailable:"):
                parts = line.split()
                if len(parts) >= 2:
                    return int(int(parts[1]) / 1024)
    try:
        pages = int(getattr(__import__("os"), "sysconf")("SC_AVPHYS_PAGES"))
        page_size = int(getattr(__import__("os"), "sysconf")("SC_PAGE_SIZE"))
        return int((pages * page_size) / (1024 * 1024))
    except Exception:
        return None


def _should_skip_docling(
    path: Path,
    *,
    docling_max_pages: int | None,
    docling_max_ram_mb: int | None,
) -> tuple[bool, str | None, int | None]:
    page_count = _pdf_page_count(path)
    if docling_max_pages is not None and page_count is not None and page_count > docling_max_pages:
        return True, "docling_max_pages", page_count
    available_ram = _available_ram_mb()
    if docling_max_ram_mb is not None and available_ram is not None and available_ram < docling_max_ram_mb:
        return True, "docling_max_ram_mb", page_count
    return False, None, page_count


def parse_pdf_with_pymupdf(
    path: Path,
    default_language: str,
    *,
    page_asset_dir: Path | None = None,
    enable_ocr: bool = True,
    ocr_text_min_chars: int = 80,
    render_page_images: bool = True,
    page_image_dpi: int = 144,
) -> DocumentRecord:
    pdf = fitz.open(path)
    doc_id = _doc_id_from_path(path)
    page_text: list[str] = []
    page_assets: list[dict[str, Any]] = []
    for page_number, page in enumerate(pdf, start=1):
        raw_text = page.get_text("text")
        normalized_text = normalize_text(raw_text)
        ocr_used = False
        if enable_ocr and len(normalized_text) < ocr_text_min_chars:
            ocr_text = normalize_text(_ocr_page_text(page))
            if len(ocr_text) > len(normalized_text):
                normalized_text = ocr_text
                ocr_used = True
        has_visual_content = _page_has_visual_content(page, raw_text)
        requires_multimodal = has_visual_content or ocr_used or len(normalized_text) < ocr_text_min_chars
        image_path: str | None = None
        if render_page_images and requires_multimodal and page_asset_dir is not None:
            image_path = str(
                _render_page_image(
                    page,
                    page_asset_dir=page_asset_dir,
                    doc_id=doc_id,
                    page_number=page_number,
                    dpi=page_image_dpi,
                ).resolve()
            )
        page_text.append(normalized_text)
        page_assets.append(
            {
                "page_number": page_number,
                "image_path": image_path,
                "ocr_used": ocr_used,
                "requires_multimodal": requires_multimodal,
                "text_chars": len(normalized_text),
            }
        )
    pdf.close()
    # Marcar ecuaciones en cada página preservando LaTeX existente.
    math_expression_count = 0
    for idx, raw_page in enumerate(page_text):
        if not raw_page:
            continue
        marked, found = mark_math(raw_page)
        if found:
            page_text[idx] = marked
            math_expression_count += found
    sections = _sections_from_pages(page_text)
    cleaned_pages = [page for page in page_text if page]
    body_text = "\n\n".join(cleaned_pages)
    detected_language = detect_language(body_text[:4000], default=default_language)
    if detected_language != default_language:
        log_event(
            logger,
            logging.INFO,
            "language_detected_override",
            source=path.name,
            configured=default_language,
            detected=detected_language,
        )
    return DocumentRecord(
        doc_id=doc_id,
        source_doc=path.name,
        file_path=str(path.resolve()),
        language=detected_language,
        text=body_text,
        sections=sections,
        page_text=page_text,
        page_assets=page_assets,
        metadata={
            "parser": "pymupdf",
            "page_count": len(page_text),
            "ocr_pages": sum(1 for asset in page_assets if asset["ocr_used"]),
            "multimodal_pages": sum(1 for asset in page_assets if asset["requires_multimodal"]),
            "math_expressions": math_expression_count,
            "language_configured": default_language,
            "language_detected": detected_language,
        },
    )


def parse_pdf(
    path: Path,
    primary_parser: str,
    fallback_parser: str,
    default_language: str,
    *,
    page_asset_dir: Path | None = None,
    enable_ocr: bool = True,
    ocr_text_min_chars: int = 80,
    render_page_images: bool = True,
    page_image_dpi: int = 144,
    docling_max_pages: int | None = None,
    docling_max_ram_mb: int | None = None,
) -> DocumentRecord:
    parser_order = [primary_parser, fallback_parser]
    last_error: Exception | None = None
    skipped_docling = False
    skip_reason: str | None = None
    skip_page_count: int | None = None
    for parser_name in parser_order:
        try:
            if parser_name == "docling":
                if not skipped_docling:
                    skipped_docling, skip_reason, skip_page_count = _should_skip_docling(
                        path,
                        docling_max_pages=docling_max_pages,
                        docling_max_ram_mb=docling_max_ram_mb,
                    )
                if skipped_docling:
                    log_event(
                        logger,
                        logging.INFO,
                        "docling_skipped_by_resource_guard",
                        source=str(path),
                        reason=skip_reason,
                        page_count=skip_page_count,
                        docling_max_pages=docling_max_pages,
                        docling_max_ram_mb=docling_max_ram_mb,
                    )
                    continue
                try:
                    from docling.document_converter import DocumentConverter  # type: ignore
                except Exception as exc:  # pragma: no cover - optional dependency
                    raise RuntimeError("docling is not installed") from exc
                converter = DocumentConverter()
                result = converter.convert(str(path))
                text = result.document.export_to_markdown()
                cleaned = normalize_text(text)
                pymupdf_record = parse_pdf_with_pymupdf(
                    path,
                    default_language=default_language,
                    page_asset_dir=page_asset_dir,
                    enable_ocr=enable_ocr,
                    ocr_text_min_chars=ocr_text_min_chars,
                    render_page_images=render_page_images,
                    page_image_dpi=page_image_dpi,
                )
                return pymupdf_record.model_copy(
                    update={
                        "text": cleaned or pymupdf_record.text,
                        "metadata": {
                            **pymupdf_record.metadata,
                            "parser": "docling",
                            "page_parser": "pymupdf",
                        },
                    }
                )
            if parser_name == "pymupdf":
                record = parse_pdf_with_pymupdf(
                    path,
                    default_language=default_language,
                    page_asset_dir=page_asset_dir,
                    enable_ocr=enable_ocr,
                    ocr_text_min_chars=ocr_text_min_chars,
                    render_page_images=render_page_images,
                    page_image_dpi=page_image_dpi,
                )
                if skipped_docling and skip_reason:
                    return record.model_copy(
                        update={
                            "metadata": {
                                **record.metadata,
                                "parser_skip_reason": skip_reason,
                            }
                        }
                    )
                return record
        except Exception as exc:  # pragma: no cover - exercised through fallback behavior
            log_event(
                logger,
                logging.WARNING,
                "parser_failed_falling_back",
                parser=parser_name,
                source=str(path),
                exc_type=type(exc).__name__,
                exc=str(exc)[:200],
            )
            last_error = exc
            continue
    log_event(
        logger,
        logging.ERROR,
        "pdf_unparseable",
        source=str(path),
        exc=str(last_error)[:200] if last_error else "unknown",
    )
    raise RuntimeError(f"Could not parse {path}") from last_error


def ingest_directory(
    *,
    pdf_dir: Path,
    primary_parser: str,
    fallback_parser: str,
    target_tokens: int,
    overlap: int,
    default_language: str,
    chunking_strategy: str = "semantic",
    recursive: bool = True,
    page_asset_dir: Path | None = None,
    enable_ocr: bool = True,
    ocr_text_min_chars: int = 80,
    render_page_images: bool = True,
    page_image_dpi: int = 144,
    max_pages_per_chunk: int | None = None,
    max_documents: int | None = None,
    docling_max_pages: int | None = None,
    docling_max_ram_mb: int | None = None,
) -> IngestResult:
    documents: list[DocumentRecord] = []
    chunks = []
    pdf_paths = discover_pdf_paths(pdf_dir, recursive=recursive)
    if max_documents is not None:
        pdf_paths = pdf_paths[: max(0, max_documents)]
    for path in pdf_paths:
        document = parse_pdf(
            path,
            primary_parser=primary_parser,
            fallback_parser=fallback_parser,
            default_language=default_language,
            page_asset_dir=page_asset_dir,
            enable_ocr=enable_ocr,
            ocr_text_min_chars=ocr_text_min_chars,
            render_page_images=render_page_images,
            page_image_dpi=page_image_dpi,
            docling_max_pages=docling_max_pages,
            docling_max_ram_mb=docling_max_ram_mb,
        )
        documents.append(document)
        chunks.extend(
            chunk_document(
                document,
                target_tokens=target_tokens,
                overlap=overlap,
                strategy=chunking_strategy,
                max_pages_per_chunk=max_pages_per_chunk,
            )
        )
    return IngestResult(documents=documents, chunks=attach_neighbors(chunks))


def discover_pdf_paths(pdf_dir: Path, *, recursive: bool = True) -> list[Path]:
    if pdf_dir.is_file():
        return [pdf_dir] if pdf_dir.suffix.lower() == ".pdf" else []
    iterator = pdf_dir.rglob("*.pdf") if recursive else pdf_dir.glob("*.pdf")
    return sorted(path for path in iterator if path.is_file())
