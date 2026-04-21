from __future__ import annotations

import logging
from typing import Any

from synthetic_ds.models import ChunkRecord, DocumentRecord
from synthetic_ds.semantic_chunking import chunk_document_semantic
from synthetic_ds.text import estimate_tokens, normalize_text


logger = logging.getLogger("chunking")


def chunk_document(
    document: DocumentRecord,
    target_tokens: int = 8192,
    overlap: int = 200,
    *,
    strategy: str | None = None,
    use_semantic: bool | None = None,
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
        if _needs_legacy_fallback(document, semantic_chunks, target_tokens):
            logger.info(
                "Fallback a chunking tradicional para %s: el chunking semántico no preservó cobertura suficiente",
                document.source_doc,
            )
            return _legacy_chunk_document(document, target_tokens=target_tokens, overlap=overlap)
        return semantic_chunks
    
    # Fallback al chunking tradicional por tokens (sin usar)
    logger.warning("Usando chunking tradicional (no recomendado)")
    return _legacy_chunk_document(document, target_tokens=target_tokens, overlap=overlap)


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
    if len(chunks) == 1 and estimate_tokens(normalized_text) > target_tokens:
        return True
    return False


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
