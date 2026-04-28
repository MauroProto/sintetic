from __future__ import annotations

import logging
import hashlib
import math
from typing import Any

from synthetic_ds.models import ChunkRecord, DocumentRecord
from synthetic_ds.semantic_chunking import chunk_document_semantic
from synthetic_ds.text import estimate_tokens, normalize_text


logger = logging.getLogger("chunking")
MIN_CHUNK_DENSITY_PAGES = 20


def chunk_document(
    document: DocumentRecord,
    target_tokens: int = 8192,
    overlap: int = 200,
    *,
    strategy: str | None = None,
    use_semantic: bool | None = None,
    max_pages_per_chunk: int | None = None,
) -> list[ChunkRecord]:
    """
    Crea chunks de un documento.
    
    Por defecto usa chunking semántico inteligente que:
    - Detecta capítulos/secciones automáticamente
    - Crea chunks de ~8K tokens (suficiente para capítulos completos)
    - Respeta estructura jerárquica del documento
    - Añade overlap semántico entre chunks
    
    Args:
        document: Documento a procesar
        target_tokens: Tamaño objetivo de cada chunk (default 8192)
        overlap: Tokens de overlap entre chunks (default 200)
        strategy: Estrategia explícita ("semantic" o "headings_first").
        use_semantic: Compatibilidad con callers antiguos.
    """
    selected_strategy = _resolve_chunking_strategy(strategy=strategy, use_semantic=use_semantic)

    if selected_strategy == "semantic":
        logger.info(f"Usando chunking semántico inteligente para {document.source_doc}")
        semantic_chunks = chunk_document_semantic(document, target_tokens=target_tokens, overlap_tokens=overlap)
        if _needs_legacy_fallback(document, semantic_chunks, target_tokens, overlap):
            logger.info(
                "Fallback a chunking tradicional para %s: el chunking semántico no preservó cobertura suficiente",
                document.source_doc,
            )
            legacy_chunks = _legacy_chunk_document(document, target_tokens=target_tokens, overlap=overlap)
            limited = _enforce_page_limit(document, legacy_chunks, max_pages_per_chunk=max_pages_per_chunk)
            dense = _enforce_min_chunk_density(document, limited)
            return _annotate_chunking_metrics(document, dense, strategy=selected_strategy)
        limited = _enforce_page_limit(document, semantic_chunks, max_pages_per_chunk=max_pages_per_chunk)
        dense = _enforce_min_chunk_density(document, limited)
        return _annotate_chunking_metrics(document, dense, strategy=selected_strategy)
    
    # Fallback al chunking tradicional por tokens (sin usar)
    logger.warning("Usando chunking tradicional (no recomendado)")
    legacy_chunks = _legacy_chunk_document(document, target_tokens=target_tokens, overlap=overlap)
    limited = _enforce_page_limit(document, legacy_chunks, max_pages_per_chunk=max_pages_per_chunk)
    dense = _enforce_min_chunk_density(document, limited)
    return _annotate_chunking_metrics(document, dense, strategy=selected_strategy)


def _resolve_chunking_strategy(*, strategy: str | None, use_semantic: bool | None) -> str:
    if strategy:
        normalized = strategy.strip().lower()
        if normalized in {"semantic", "headings_first"}:
            return normalized
        logger.warning("Estrategia de chunking desconocida '%s'; usando semantic", strategy)
        return "semantic"
    if use_semantic is not None:
        return "semantic" if use_semantic else "headings_first"
    return "semantic"


def _needs_legacy_fallback(
    document: DocumentRecord,
    chunks: list[ChunkRecord],
    target_tokens: int,
    overlap: int,
) -> bool:
    if not chunks:
        return True
    if document.sections:
        return False
    if len(document.page_text) <= 1:
        return False

    last_page = len(document.page_text)
    if chunks[-1].page_range[1] < last_page:
        return True

    normalized_text = normalize_text(document.text)
    total_tokens = estimate_tokens(normalized_text)
    if len(chunks) == 1 and total_tokens > target_tokens:
        return True
    if total_tokens > target_tokens:
        stride = max(1, target_tokens - max(0, overlap))
        expected_windows = 1 + math.ceil(max(0, total_tokens - target_tokens) / stride)
        if len(chunks) < expected_windows:
            return True
    return False


def _chunk_metadata_for_pages(
    document: DocumentRecord,
    page_start: int,
    page_end: int,
    base_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    relevant_assets = [
        asset
        for asset in document.page_assets
        if page_start <= int(asset.get("page_number", 0)) <= page_end
    ]
    metadata = dict(base_metadata or {})
    metadata.update(
        {
            "page_image_paths": [str(asset["image_path"]) for asset in relevant_assets if asset.get("image_path")],
            "requires_multimodal": any(bool(asset.get("requires_multimodal")) for asset in relevant_assets),
            "uses_ocr": any(bool(asset.get("ocr_used")) for asset in relevant_assets),
        }
    )
    return metadata


def _connect_neighbors(chunks: list[ChunkRecord]) -> list[ChunkRecord]:
    connected: list[ChunkRecord] = []
    for index, chunk in enumerate(chunks):
        neighbors = []
        if index > 0:
            neighbors.append(chunks[index - 1].chunk_id)
        if index < len(chunks) - 1:
            neighbors.append(chunks[index + 1].chunk_id)
        connected.append(chunk.model_copy(update={"neighbors": neighbors}))
    return connected


def _enforce_page_limit(
    document: DocumentRecord,
    chunks: list[ChunkRecord],
    *,
    max_pages_per_chunk: int | None,
) -> list[ChunkRecord]:
    if max_pages_per_chunk is None or max_pages_per_chunk <= 0:
        return chunks
    if not chunks or not document.page_text:
        return chunks

    limited: list[ChunkRecord] = []
    for chunk in chunks:
        page_start, page_end = chunk.page_range
        if page_end < page_start or (page_end - page_start + 1) <= max_pages_per_chunk:
            limited.append(chunk)
            continue

        split_parts: list[ChunkRecord] = []
        current_start = page_start
        ordinal = 1
        while current_start <= page_end:
            current_end = min(page_end, current_start + max_pages_per_chunk - 1)
            page_texts = [
                normalize_text(document.page_text[page_number - 1])
                for page_number in range(current_start, current_end + 1)
                if 0 <= page_number - 1 < len(document.page_text)
                and normalize_text(document.page_text[page_number - 1])
            ]
            window_text = "\n\n".join(page_texts).strip()
            if window_text:
                chunk_id = f"{chunk.chunk_id}-p{current_start:04d}-{current_end:04d}"
                split_parts.append(
                    ChunkRecord(
                        chunk_id=chunk_id,
                        doc_id=chunk.doc_id,
                        source_doc=chunk.source_doc,
                        section_path=chunk.section_path,
                        page_range=(current_start, current_end),
                        text=window_text,
                        token_count=estimate_tokens(window_text),
                        text_hash=hashlib.sha1(window_text.encode("utf-8")).hexdigest(),
                        neighbors=[],
                        metadata={
                            **_chunk_metadata_for_pages(
                                document,
                                current_start,
                                current_end,
                                base_metadata=chunk.metadata,
                            ),
                            "split_reason": "max_pages_per_chunk",
                            "parent_chunk_id": chunk.chunk_id,
                            "split_part": ordinal,
                        },
                    )
                )
                ordinal += 1
            current_start = current_end + 1

        limited.extend(split_parts or [chunk])

    return _connect_neighbors(limited)


def _expected_min_chunks_for_pages(page_count: int) -> int:
    if page_count <= 1:
        return 1
    return max(2, math.ceil(page_count / MIN_CHUNK_DENSITY_PAGES))


def _page_window_chunks(
    document: DocumentRecord,
    *,
    max_pages_per_chunk: int,
    split_reason: str,
    base_metadata: dict[str, Any] | None = None,
) -> list[ChunkRecord]:
    chunks: list[ChunkRecord] = []
    page_count = len(document.page_text)
    ordinal = 1
    current_start = 1
    while current_start <= page_count:
        current_end = min(page_count, current_start + max_pages_per_chunk - 1)
        page_texts = [
            normalize_text(document.page_text[page_number - 1])
            for page_number in range(current_start, current_end + 1)
            if normalize_text(document.page_text[page_number - 1])
        ]
        window_text = "\n\n".join(page_texts).strip()
        if window_text:
            chunk_id = hashlib.sha1(
                f"{document.doc_id}-{split_reason}-{current_start}-{current_end}-{window_text}".encode("utf-8")
            ).hexdigest()[:12]
            chunks.append(
                ChunkRecord(
                    chunk_id=f"{document.doc_id}-chunk-{ordinal:04d}-{chunk_id}",
                    doc_id=document.doc_id,
                    source_doc=document.source_doc,
                    section_path=[],
                    page_range=(current_start, current_end),
                    text=window_text,
                    token_count=estimate_tokens(window_text),
                    text_hash=hashlib.sha1(window_text.encode("utf-8")).hexdigest(),
                    neighbors=[],
                    metadata={
                        **_chunk_metadata_for_pages(
                            document,
                            current_start,
                            current_end,
                            base_metadata=base_metadata,
                        ),
                        "split_reason": split_reason,
                        "split_part": ordinal,
                    },
                )
            )
            ordinal += 1
        current_start = current_end + 1
    return _connect_neighbors(chunks)


def _enforce_min_chunk_density(document: DocumentRecord, chunks: list[ChunkRecord]) -> list[ChunkRecord]:
    if not chunks or document.sections or not document.page_text:
        return chunks
    page_count = len(document.page_text)
    expected_min_chunks = _expected_min_chunks_for_pages(page_count)
    if len(chunks) >= expected_min_chunks:
        return chunks
    max_pages_per_chunk = max(1, math.floor(page_count / expected_min_chunks))
    logger.warning(
        "Cobertura de chunks baja en %s: %s chunks para %s paginas; rehaciendo ventanas de %s paginas",
        document.source_doc,
        len(chunks),
        page_count,
        max_pages_per_chunk,
    )
    return _page_window_chunks(
        document,
        max_pages_per_chunk=max_pages_per_chunk,
        split_reason="min_chunk_density",
        base_metadata={"low_chunk_density_fallback": True},
    )


def _chunk_coverage_metrics(document: DocumentRecord, chunks: list[ChunkRecord]) -> dict[str, Any]:
    page_count = len(document.page_text) or int(document.metadata.get("page_count", 0) or 0)
    covered_pages: set[int] = set()
    for chunk in chunks:
        page_start, page_end = chunk.page_range
        covered_pages.update(range(max(1, page_start), max(page_start, page_end) + 1))
    coverage_ratio = (len(covered_pages) / page_count) if page_count else 0.0
    return {
        "page_count": page_count,
        "pages_covered": len(covered_pages),
        "coverage_ratio": round(coverage_ratio, 4),
        "chunk_count": len(chunks),
        "expected_min_chunks": _expected_min_chunks_for_pages(page_count),
    }


def _annotate_chunking_metrics(document: DocumentRecord, chunks: list[ChunkRecord], *, strategy: str) -> list[ChunkRecord]:
    metrics = _chunk_coverage_metrics(document, chunks)
    if metrics["page_count"] and (
        metrics["coverage_ratio"] < 0.15 or metrics["chunk_count"] < metrics["expected_min_chunks"]
    ):
        logger.warning(
            "Cobertura baja en %s: chunks=%s paginas_cubiertas=%s/%s ratio=%.2f estrategia=%s",
            document.source_doc,
            metrics["chunk_count"],
            metrics["pages_covered"],
            metrics["page_count"],
            metrics["coverage_ratio"],
            strategy,
        )
    return [
        chunk.model_copy(
            update={
                "metadata": {
                    **chunk.metadata,
                    **metrics,
                    "chunking_strategy": strategy,
                }
            }
        )
        for chunk in chunks
    ]


def _legacy_chunk_document(
    document: DocumentRecord,
    target_tokens: int = 512,
    overlap: int = 50,
) -> list[ChunkRecord]:
    """Chunking tradicional por tokens (mantenido por compatibilidad)."""
    from synthetic_ds.models import DocumentSection
    import hashlib
    
    def _make_chunk_id(doc_id: str, ordinal: int, text: str) -> str:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
        return f"{doc_id}-chunk-{ordinal:04d}-{digest}"
    
    def _make_hash(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()
    
    def _chunk_metadata(document: DocumentRecord, page_start: int, page_end: int) -> dict[str, Any]:
        relevant_assets = [
            asset
            for asset in document.page_assets
            if page_start <= int(asset.get("page_number", 0)) <= page_end
        ]
        page_image_paths = [str(asset["image_path"]) for asset in relevant_assets if asset.get("image_path")]
        return {
            "page_image_paths": page_image_paths,
            "requires_multimodal": any(bool(asset.get("requires_multimodal")) for asset in relevant_assets),
            "uses_ocr": any(bool(asset.get("ocr_used")) for asset in relevant_assets),
        }
    
    chunks: list[ChunkRecord] = []
    ordinal = 1
    
    for raw_section in document.sections:
        section = raw_section if isinstance(raw_section, DocumentSection) else DocumentSection.model_validate(raw_section)
        cleaned = normalize_text(section.text)
        if estimate_tokens(cleaned) <= target_tokens:
            chunks.append(
                ChunkRecord(
                    chunk_id=_make_chunk_id(document.doc_id, ordinal, cleaned),
                    doc_id=document.doc_id,
                    source_doc=document.source_doc,
                    section_path=[section.heading],
                    page_range=(section.page_start, section.page_end),
                    text=cleaned,
                    token_count=estimate_tokens(cleaned),
                    text_hash=_make_hash(cleaned),
                    neighbors=[],
                    metadata=_chunk_metadata(document, section.page_start, section.page_end),
                )
            )
            ordinal += 1
            continue

        tokens = cleaned.split()
        start = 0
        while start < len(tokens):
            end = min(len(tokens), start + target_tokens)
            window = " ".join(tokens[start:end]).strip()
            chunks.append(
                ChunkRecord(
                    chunk_id=_make_chunk_id(document.doc_id, ordinal, window),
                    doc_id=document.doc_id,
                    source_doc=document.source_doc,
                    section_path=[section.heading],
                    page_range=(section.page_start, section.page_end),
                    text=window,
                    token_count=estimate_tokens(window),
                    text_hash=_make_hash(window),
                    neighbors=[],
                    metadata=_chunk_metadata(document, section.page_start, section.page_end),
                )
            )
            ordinal += 1
            if end == len(tokens):
                break
            start = max(end - overlap, start + 1)

    if chunks:
        return chunks

    page_tokens: list[tuple[str, int]] = []
    for page_number, page_text in enumerate(document.page_text, start=1):
        cleaned_page = normalize_text(page_text)
        if not cleaned_page:
            continue
        page_tokens.extend((token, page_number) for token in cleaned_page.split())

    if not page_tokens:
        cleaned = normalize_text(document.text)
        if not cleaned:
            return []
        page_tokens = [(token, 1) for token in cleaned.split()]

    start = 0
    while start < len(page_tokens):
        end = min(len(page_tokens), start + target_tokens)
        window_items = page_tokens[start:end]
        window = " ".join(token for token, _page in window_items).strip()
        page_start = window_items[0][1]
        page_end = window_items[-1][1]
        chunks.append(
            ChunkRecord(
                chunk_id=_make_chunk_id(document.doc_id, ordinal, window),
                doc_id=document.doc_id,
                source_doc=document.source_doc,
                section_path=[],
                page_range=(page_start, page_end),
                text=window,
                token_count=estimate_tokens(window),
                text_hash=_make_hash(window),
                neighbors=[],
                metadata=_chunk_metadata(document, page_start, page_end),
            )
        )
        ordinal += 1
        if end == len(page_tokens):
            break
        start = max(end - overlap, start + 1)
    
    return chunks
