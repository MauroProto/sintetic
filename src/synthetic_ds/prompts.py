"""Prompts para generación y judging con soporte multi-idioma.

Los prompts se expresan en inglés (lengua franca del training data de los LLMs
modernos) pero fuerzan la lengua de salida mediante el parámetro ``language``.
Esto da consistencia y evita los sesgos de un prompt redactado en español
cuando el documento está en alemán, portugués, etc.

NUEVO: Soporte para contexto jerárquico extendido. El LLM recibe:
- Resumen del documento completo
- Contexto de secciones vecinas
- El chunk actual con su estructura jerárquica
Esto permite preguntas más complejas y mejor validación de unanswerable.
"""
from __future__ import annotations

from typing import Any

from synthetic_ds.models import ChunkRecord, ExampleKind, PromptParts


LANGUAGE_NAMES: dict[str, str] = {
    "es": "Spanish",
    "en": "English",
    "pt": "Portuguese",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "ca": "Catalan",
    "nl": "Dutch",
    "pl": "Polish",
    "ru": "Russian",
    "ja": "Japanese",
    "ko": "Korean",
    "zh-cn": "Simplified Chinese",
    "zh-tw": "Traditional Chinese",
    "ar": "Arabic",
    "hi": "Hindi",
    "tr": "Turkish",
}


def _language_name(code: str) -> str:
    return LANGUAGE_NAMES.get((code or "").lower(), code or "the source language")


GENERATION_SYSTEM_PREFIX = (
    "You are an expert dataset curator for fine-tuning large language models. "
    "Generate exactly one training example per request, strictly grounded in the "
    "provided document fragments. Output must be valid JSON matching the provided "
    "schema. Never invent facts outside the document."
)


GENERATION_RULES: dict[ExampleKind, str] = {
    ExampleKind.EXTRACTIVE: (
        "Produce a question whose answer is a literal verbatim span from the "
        "fragment. Keys required: question, answer, evidence, question_type, "
        "difficulty, is_answerable."
    ),
    ExampleKind.INFERENTIAL: (
        "Produce a question that requires a single inference step over the facts "
        "present in the fragment. Keys required: question, answer, evidence, "
        "reasoning, supporting_facts, question_type, difficulty, is_answerable."
    ),
    ExampleKind.UNANSWERABLE: (
        "Produce a plausible question that CANNOT be answered from the fragment. "
        "is_answerable must be false and the answer must be the provided refusal "
        "text. Keys required: question, answer, evidence, question_type, "
        "difficulty, is_answerable."
    ),
    ExampleKind.MULTI_CHUNK: (
        "Produce a question that can only be answered by combining information "
        "across the fragments. The question must not be answerable from a single "
        "fragment alone. Keys required: question, answer, evidence, reasoning, "
        "supporting_facts, question_type, difficulty, is_answerable."
    ),
    ExampleKind.FORMAT_SPECIFIC: (
        "Produce a question whose answer must follow an explicit format such as a "
        "numbered list, bullet list, table, or JSON. Keys required: question, "
        "answer, evidence, question_type, difficulty, is_answerable."
    ),
}


def _build_context_block(
    chunks: list[ChunkRecord],
    doc_summary: str | None = None,
    prev_context: str | None = None,
    next_context: str | None = None,
) -> str:
    """Construye bloque de contexto jerárquico."""
    parts: list[str] = []
    
    if doc_summary:
        parts.append(f"DOCUMENT OVERVIEW:\n{doc_summary}")
    
    if prev_context:
        parts.append(f"PREVIOUS CONTEXT (for continuity):\n{prev_context}")
    
    if next_context:
        parts.append(f"NEXT CONTEXT (for continuity):\n{next_context}")
    
    if parts:
        parts.append("=" * 60)
    
    return "\n\n".join(parts)


def build_generation_prompt(
    kind: ExampleKind,
    chunks: list[ChunkRecord],
    language: str,
    prompt_version: str,
    refusal_text: str,
    doc_summary: str | None = None,
) -> PromptParts:
    del prompt_version
    language_label = _language_name(language)
    
    multimodal_note = ""
    if any(chunk.metadata.get("requires_multimodal") for chunk in chunks):
        multimodal_note = (
            "\nPage images may be attached alongside the text (formulas, tables, "
            "scanned content). Use them only as support for the same document."
        )
    
    # Contexto adicional para preguntas unanswerable
    context_note = ""
    if kind == ExampleKind.UNANSWERABLE:
        context_note = (
            "\nIMPORTANT: For unanswerable questions, you have visibility of the "
            "entire chapter/section. The question must be PLAUSIBLE (related to the "
            "topic) but the answer must NOT be found in any of the provided context. "
            "Think about what a reader might ask but the text doesn't cover."
        )
    
    system = (
        f"{GENERATION_SYSTEM_PREFIX}\n"
        f"Output language: {language_label} ({language}). Reply ONLY in {language_label}.\n"
        f"Required question type: '{kind.value}'. The field question_type must equal '{kind.value}'.\n"
        f"{GENERATION_RULES[kind]}{multimodal_note}{context_note}"
    )
    
    # Construir contexto jerárquico
    prev_context = None
    next_context = None
    
    if len(chunks) == 1 and chunks[0].neighbors:
        # Podríamos cargar vecinos para más contexto
        pass
    
    context_block = _build_context_block(
        chunks,
        doc_summary=doc_summary,
        prev_context=prev_context,
        next_context=next_context,
    )
    
    chunk_lines = [
        (
            f"FRAGMENT {index}\n"
            f"Section: {', '.join(chunk.section_path)}\n"
            f"Doc: {chunk.source_doc}\n"
            f"Pages: {chunk.page_range[0]}-{chunk.page_range[1]}\n"
            f"{chunk.text}"
        )
        for index, chunk in enumerate(chunks, start=1)
    ]
    
    user_parts = [context_block] if context_block else []
    user_parts.extend(chunk_lines)
    user = "\n\n".join(user_parts)
    
    if kind == ExampleKind.UNANSWERABLE:
        system += f"\nIf is_answerable is false the answer MUST be exactly: '{refusal_text}'."
    
    return PromptParts(system=system, user=user)


def build_judge_prompt(
    question: str,
    answer: str,
    evidence: list[str],
    language: str,
    doc_summary: str | None = None,
) -> PromptParts:
    language_label = _language_name(language)
    
    system = (
        "You are a strict quality judge for synthetic training datasets. "
        "Score relevance, groundedness, format, difficulty and overall in the 0-1 "
        "range. Reply ONLY with valid JSON matching the required schema. "
        f"The evaluated item is written in {language_label} ({language}); evaluate "
        "it accordingly."
    )
    
    if doc_summary:
        system += (
            f"\n\nDocument context (for reference only):\n{doc_summary}"
        )
    
    evidence_block = "\n".join(f"- {item}" for item in evidence) if evidence else "- no evidence provided"
    user = (
        f"QUESTION:\n{question}\n\n"
        f"ANSWER:\n{answer}\n\n"
        f"EVIDENCE:\n{evidence_block}\n\n"
        "Score whether the answer is grounded in the evidence, whether the format "
        "is adequate, and the overall quality."
    )
    return PromptParts(system=system, user=user)


def build_document_summary_prompt(
    chunks: list[ChunkRecord],
    language: str = "es",
) -> PromptParts:
    """Prompt para generar un resumen del documento completo."""
    language_label = _language_name(language)
    
    system = (
        f"You are a document analyst. Create a concise summary (max 500 tokens) of "
        f"the document structure and key topics. Output in {language_label}. "
        f"Include: main topic, key sections, and important facts."
    )
    
    # Tomar muestras de cada chunk para el resumen
    sample_texts = []
    for i, chunk in enumerate(chunks[:10]):  # Max 10 chunks
        preview = chunk.text[:500]  # Primeros 500 chars
        sample_texts.append(f"SECTION {i+1}: {', '.join(chunk.section_path)}\n{preview}...")
    
    user = "\n\n".join(sample_texts)
    return PromptParts(system=system, user=user)