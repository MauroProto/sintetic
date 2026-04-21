from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from synthetic_ds.models import ChunkRecord, DocumentRecord, DocumentSection
from synthetic_ds.text import estimate_tokens, normalize_text


logger = logging.getLogger("semantic_chunking")

# Umbrales para chunking inteligente
MIN_CHUNK_TOKENS = 256  # Mínimo para considerar un chunk válido
MAX_CHUNK_TOKENS = 12288  # ~8000-12000 tokens, suficiente para capítulos completos
CHAPTER_MIN_TOKENS = 512  # Mínimo para considerar algo como "capítulo"
OVERLAP_TOKENS = 200  # Overlap semántico entre chunks (párrafos)


@dataclass
class SemanticSection:
    """Una sección semántica detectada en el documento."""
    heading: str
    level: int  # 0=documento, 1=capítulo, 2=sección, 3=subsección
    text: str = ""
    page_start: int = 1
    page_end: int = 1
    token_count: int = 0
    children: list["SemanticSection"] = field(default_factory=list)
    
    @property
    def full_text(self) -> str:
        """Texto completo incluyendo subsecciones."""
        texts = [self.text] if self.text else []
        for child in self.children:
            child_text = child.full_text
            if child_text:
                texts.append(child_text)
        return "\n\n".join(texts)
    
    @property
    def total_tokens(self) -> int:
        """Tokens totales incluyendo subsecciones."""
        return estimate_tokens(self.full_text)


def _detect_heading_level(line: str) -> tuple[int, str] | None:
    """
    Detecta si una línea es un encabezado y su nivel jerárquico.
    
    Retorna (nivel, título_limpio) o None si no es encabezado.
    """
    stripped = line.strip()
    if not stripped:
        return None
    
    # Patrones de encabezado
    # Capítulo: "Capítulo 1", "Chapter 1", "1.", "1 -", etc.
    chapter_patterns = [
        r'^Cap[ií]tulo\s+[\dIVX]+[\s:.-]*(.+)$',
        r'^Chapter\s+[\dIVX]+[\s:.-]*(.+)$',
        r'^(?:\d+|[IVX]+)\s*[.:-]\s+(.+)$',  # "1. Introducción" o "I. Introducción"
        r'^[\d.]+\s+(.+)$',  # "1.1 Introducción"
        r'^\d+\s*[-–—]\s*(.+)$',  # "1 - Introducción"
    ]
    
    for pattern in chapter_patterns:
        match = re.match(pattern, stripped, re.IGNORECASE)
        if match:
            title = match.group(1).strip()
            # Determinar nivel por el patrón
            if 'Capítulo' in stripped or 'Chapter' in stripped or re.match(r'^[IVX]+', stripped):
                return (1, title)
            elif re.match(r'^\d+\s*[.:-]', stripped):
                # Contar puntos para determinar nivel: 1.1.1 = nivel 3
                num_part = stripped.split()[0]
                dots = num_part.count('.')
                return (min(2 + dots, 3), title)
            else:
                return (2, title)
    
    # Markdown headers: # ## ###
    if stripped.startswith('#'):
        level = len(stripped) - len(stripped.lstrip('#'))
        title = stripped.lstrip('#').strip()
        return (min(level, 3), title)
    
    # MAYÚSCULAS como encabezado (pero no todo el documento)
    if stripped.isupper() and len(stripped) > 3 and len(stripped) < 100:
        return (2, stripped.title())
    
    # Negrita o centrado (heurística: línea corta, sin puntuación al final)
    if len(stripped) < 80 and not stripped[-1] in '.,;:' and len(stripped.split()) > 1:
        words = stripped.split()
        # Si empieza con mayúscula y tiene pocas palabras
        if words[0][0].isupper() and len(words) <= 10:
            # Verificar que no sea una oración normal
            if not any(w.lower() in ['el', 'la', 'los', 'las', 'un', 'una', 'es', 'son', 'está', 'este'] for w in words[:3]):
                return (2, stripped)
    
    return None


def _build_semantic_tree(page_texts: list[str]) -> list[SemanticSection]:
    """
    Construye un árbol semántico del documento detectando capítulos y secciones.
    """
    if not page_texts:
        return []
    
    root = SemanticSection(heading="Documento", level=0)
    current_chapter: SemanticSection | None = None
    current_section: SemanticSection | None = None
    
    for page_num, page_text in enumerate(page_texts, 1):
        lines = page_text.split('\n')
        current_paragraph: list[str] = []
        
        for line in lines:
            heading_info = _detect_heading_level(line)
            
            if heading_info:
                level, title = heading_info
                
                # Guardar párrafo acumulado
                if current_paragraph:
                    para_text = ' '.join(current_paragraph)
                    if current_section:
                        current_section.text += (' ' + para_text if current_section.text else para_text)
                    elif current_chapter:
                        current_chapter.text += (' ' + para_text if current_chapter.text else para_text)
                    else:
                        root.text += (' ' + para_text if root.text else para_text)
                    current_paragraph = []
                
                # Crear nueva sección según nivel
                new_section = SemanticSection(
                    heading=title,
                    level=level,
                    page_start=page_num,
                    page_end=page_num
                )
                
                if level == 1:
                    # Nuevo capítulo
                    root.children.append(new_section)
                    current_chapter = new_section
                    current_section = None
                elif level == 2:
                    # Nueva sección
                    if current_chapter is None:
                        # Crear capítulo implícito
                        current_chapter = SemanticSection(
                            heading="Contenido",
                            level=1,
                            page_start=page_num
                        )
                        root.children.append(current_chapter)
                    current_chapter.children.append(new_section)
                    current_section = new_section
                else:
                    # Subsección
                    if current_section is None:
                        if current_chapter is None:
                            current_chapter = SemanticSection(
                                heading="Contenido",
                                level=1,
                                page_start=page_num
                            )
                            root.children.append(current_chapter)
                        current_section = SemanticSection(
                            heading="Sección",
                            level=2,
                            page_start=page_num
                        )
                        current_chapter.children.append(current_section)
                    current_section.children.append(new_section)
            else:
                current_paragraph.append(line)
        
        # Guardar último párrafo de la página
        if current_paragraph:
            para_text = ' '.join(current_paragraph)
            if current_section:
                current_section.text += (' ' + para_text if current_section.text else para_text)
            elif current_chapter:
                current_chapter.text += (' ' + para_text if current_chapter.text else para_text)
            else:
                root.text += (' ' + para_text if root.text else para_text)
    
    # Actualizar rangos de página
    for chapter in root.children:
        if chapter.children:
            chapter.page_end = max(child.page_end for child in chapter.children)
        for section in chapter.children:
            if section.children:
                section.page_end = max(child.page_end for child in section.children)
    
    return root.children if root.children else [root]


def _merge_small_sections(sections: list[SemanticSection], min_tokens: int) -> list[SemanticSection]:
    """
    Fusiona secciones pequeñas con sus vecinas para crear chunks más grandes.
    """
    if not sections:
        return []
    
    merged: list[SemanticSection] = []
    buffer: SemanticSection | None = None
    
    for section in sections:
        if buffer is None:
            buffer = SemanticSection(
                heading=section.heading,
                level=section.level,
                text=section.full_text,
                page_start=section.page_start,
                page_end=section.page_end,
            )
        elif estimate_tokens(buffer.full_text) < min_tokens:
            # Fusionar con buffer existente
            buffer.heading += f" / {section.heading}"
            buffer.text += f"\n\n{section.full_text}"
            buffer.page_end = section.page_end
        else:
            # Buffer suficientemente grande, guardarlo
            merged.append(buffer)
            buffer = SemanticSection(
                heading=section.heading,
                level=section.level,
                text=section.full_text,
                page_start=section.page_start,
                page_end=section.page_end,
            )
    
    if buffer:
        if merged and estimate_tokens(buffer.full_text) < min_tokens:
            # Fusionar último con anterior
            last = merged[-1]
            last.heading += f" / {buffer.heading}"
            last.text += f"\n\n{buffer.full_text}"
            last.page_end = buffer.page_end
        else:
            merged.append(buffer)
    
    return merged


def _split_large_section(section: SemanticSection, max_tokens: int) -> list[SemanticSection]:
    """
    Divide una sección muy grande en partes coherentes.
    Intenta respetar párrafos y puntos naturales.
    """
    total_tokens = estimate_tokens(section.full_text)
    if total_tokens <= max_tokens:
        return [section]
    
    parts: list[SemanticSection] = []
    text = section.full_text
    
    # Dividir por párrafos dobles (saltos de línea)
    paragraphs = re.split(r'\n\s*\n', text)
    
    current_text = ""
    current_start = section.page_start
    part_num = 1
    
    for i, para in enumerate(paragraphs):
        para = para.strip()
        if not para:
            continue
        
        test_text = current_text + "\n\n" + para if current_text else para
        if estimate_tokens(test_text) > max_tokens and current_text:
            # Guardar parte actual y empezar nueva
            parts.append(SemanticSection(
                heading=f"{section.heading} (Parte {part_num})",
                level=section.level,
                text=current_text,
                page_start=current_start,
                page_end=section.page_start + (i * (section.page_end - section.page_start) // len(paragraphs)),
            ))
            current_text = para
            current_start = section.page_start + (i * (section.page_end - section.page_start) // len(paragraphs))
            part_num += 1
        else:
            current_text = test_text
    
    if current_text:
        parts.append(SemanticSection(
            heading=f"{section.heading} (Parte {part_num})" if part_num > 1 else section.heading,
            level=section.level,
            text=current_text,
            page_start=current_start,
            page_end=section.page_end,
        ))
    
    return parts


def create_semantic_chunks(
    document: DocumentRecord,
    target_tokens: int = 8192,
    overlap_tokens: int = 200,
) -> list[ChunkRecord]:
    """
    Crea chunks inteligentes respetando la estructura del documento.
    
    Estrategia:
    1. Detectar estructura jerárquica (capítulos/secciones)
    2. Fusionar secciones pequeñas para alcanzar target_tokens
    3. Dividir secciones muy grandes respetando párrafos
    4. Añadir overlap semántico entre chunks consecutivos
    """
    chunks: list[ChunkRecord] = []
    
    # Usar estructura existente si está disponible
    if document.sections and len(document.sections) > 1:
        # Convertir secciones existentes a chunks
        sections = []
        for raw_section in document.sections:
            if isinstance(raw_section, dict):
                raw_section = DocumentSection.model_validate(raw_section)
            sections.append(SemanticSection(
                heading=raw_section.heading,
                level=2,
                text=normalize_text(raw_section.text),
                page_start=raw_section.page_start,
                page_end=raw_section.page_end,
            ))
    else:
        # Detectar estructura desde el texto
        sections = _build_semantic_tree(document.page_text)
    
    # Fusionar secciones pequeñas
    sections = _merge_small_sections(sections, target_tokens // 2)
    
    # Dividir secciones muy grandes
    final_sections: list[SemanticSection] = []
    for section in sections:
        if section.total_tokens > target_tokens:
            final_sections.extend(_split_large_section(section, target_tokens))
        else:
            final_sections.append(section)
    
    # Crear chunks con overlap
    for i, section in enumerate(final_sections):
        text = section.full_text
        
        # Agregar overlap del chunk anterior
        if i > 0 and overlap_tokens > 0:
            prev_text = final_sections[i-1].full_text
            prev_words = prev_text.split()
            overlap_words = prev_words[-overlap_tokens:] if len(prev_words) > overlap_tokens else prev_words
            overlap_text = ' '.join(overlap_words)
            if overlap_text:
                text = f"[Continuación del tema anterior]\n{overlap_text}\n\n---\n\n{text}"
        
        # Calcular metadatos
        page_start = section.page_start
        page_end = section.page_end
        
        chunk_id = hashlib.sha1(
            f"{document.doc_id}-{i}-{section.heading}".encode()
        ).hexdigest()[:12]
        
        chunk = ChunkRecord(
            chunk_id=f"{document.doc_id}-chunk-{i:04d}-{chunk_id}",
            doc_id=document.doc_id,
            source_doc=document.source_doc,
            section_path=[section.heading],
            page_range=(page_start, page_end),
            text=text,
            token_count=estimate_tokens(text),
            text_hash=hashlib.sha1(text.encode()).hexdigest(),
            neighbors=[],
            metadata={
                "semantic_level": section.level,
                "heading": section.heading,
                "page_image_paths": [
                    str(asset["image_path"]) 
                    for asset in document.page_assets 
                    if page_start <= int(asset.get("page_number", 0)) <= page_end 
                    and asset.get("image_path")
                ],
                "requires_multimodal": any(
                    bool(asset.get("requires_multimodal")) 
                    for asset in document.page_assets 
                    if page_start <= int(asset.get("page_number", 0)) <= page_end
                ),
            }
        )
        chunks.append(chunk)
    
    # Conectar vecinos
    for i in range(len(chunks)):
        neighbors = []
        if i > 0:
            neighbors.append(chunks[i-1].chunk_id)
        if i < len(chunks) - 1:
            neighbors.append(chunks[i+1].chunk_id)
        chunks[i] = chunks[i].model_copy(update={"neighbors": neighbors})
    
    logger.info(
        f"Documento {document.source_doc}: {len(chunks)} chunks semánticos creados "
        f"(target={target_tokens} tokens, max={MAX_CHUNK_TOKENS})"
    )
    
    return chunks


def chunk_document_semantic(
    document: DocumentRecord,
    target_tokens: int = 8192,
    overlap_tokens: int = 200,
) -> list[ChunkRecord]:
    """Entry point para chunking semántico inteligente."""
    return create_semantic_chunks(
        document,
        target_tokens=target_tokens,
        overlap_tokens=overlap_tokens,
    )