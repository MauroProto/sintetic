from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Protocol

from synthetic_ds.models import ChunkRecord, ExampleKind, GeneratedExample, GenerationTarget, JudgeScore
from synthetic_ds.prompts import build_document_summary_prompt, build_generation_prompt, build_judge_prompt


GENERATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "question": {"type": "string"},
        "answer": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": ["string", "null"]},
        "supporting_facts": {"type": "array", "items": {"type": "string"}},
        "question_type": {"type": "string"},
        "difficulty": {"type": "string"},
        "is_answerable": {"type": "boolean"},
    },
    "required": ["question", "answer", "evidence", "question_type", "difficulty", "is_answerable"],
    "additionalProperties": False,
}

JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "relevance": {"type": "number"},
        "groundedness": {"type": "number"},
        "format": {"type": "number"},
        "difficulty": {"type": "number"},
        "overall": {"type": "number"},
        "rationale": {"type": "string"},
    },
    "required": ["relevance", "groundedness", "format", "difficulty", "overall", "rationale"],
    "additionalProperties": False,
}


class StructuredGenerationBackend(Protocol):
    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        session_id: str,
    ) -> dict[str, Any]: ...


def _backend_generate_structured(backend: StructuredGenerationBackend, **kwargs: Any) -> dict[str, Any]:
    try:
        return backend.generate_structured(**kwargs)
    except TypeError as exc:
        if "user_parts" not in kwargs or "user_parts" not in str(exc):
            raise
        fallback_kwargs = dict(kwargs)
        fallback_kwargs.pop("user_parts", None)
        return backend.generate_structured(**fallback_kwargs)


def _expand_mix(mix: dict[str, float]) -> list[ExampleKind]:
    slots: list[ExampleKind] = []
    for key, weight in mix.items():
        slots.extend([ExampleKind(key)] * max(1, round(weight * 100)))
    return slots or [ExampleKind.EXTRACTIVE]


def _kind_for_index(index: int, mix: dict[str, float]) -> ExampleKind:
    cycle = _expand_mix(mix)
    return cycle[index % len(cycle)]


def _example_id(question: str, chunk_ids: list[str]) -> str:
    material = "|".join(chunk_ids) + "|" + question
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:12]


def normalize_question_type(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "fact": "extractive",
        "factoid": "extractive",
        "factual": "extractive",
        "literal": "extractive",
        "extractive": "extractive",
        "extractive_qa": "extractive",
        "inferential": "inferential",
        "inference": "inferential",
        "unanswerable": "unanswerable",
        "trap": "unanswerable",
        "multi_chunk": "multi_chunk",
        "multihop": "multi_chunk",
        "multi_hop": "multi_chunk",
        "format_specific": "format_specific",
        "formatted": "format_specific",
    }
    return aliases.get(normalized, normalized)


def _active_kinds(mix: dict[str, float]) -> list[ExampleKind]:
    active: list[ExampleKind] = []
    for key, weight in mix.items():
        if weight <= 0:
            continue
        active.append(ExampleKind(key))
    return active or [ExampleKind.EXTRACTIVE]


def _target_kind_counts(total: int, mix: dict[str, float]) -> dict[ExampleKind, int]:
    active_kinds = _active_kinds(mix)
    weights = {kind: max(mix.get(kind.value, 0.0), 0.0) for kind in active_kinds}
    counts = {kind: 0 for kind in active_kinds}
    remaining = total

    if total >= len(active_kinds):
        for kind in active_kinds:
            counts[kind] = 1
            remaining -= 1

    if remaining <= 0:
        return counts

    total_weight = sum(weights.values()) or float(len(active_kinds))
    remainders: list[tuple[float, ExampleKind]] = []
    distributed = 0
    for kind in active_kinds:
        exact = remaining * (weights[kind] / total_weight)
        base = int(exact)
        counts[kind] += base
        distributed += base
        remainders.append((exact - base, kind))
    for _remainder, kind in sorted(remainders, reverse=True):
        if distributed >= remaining:
            break
        counts[kind] += 1
        distributed += 1
    return counts


def _score_chunk_for_kind(chunk: ChunkRecord, kind: ExampleKind) -> tuple[int, int]:
    text = chunk.text.lower()
    number_count = sum(any(char.isdigit() for char in token) for token in text.split())
    has_list = "1." in text or "2." in text or "3." in text
    has_comparison = any(
        marker in text for marker in ("diferencia", "compar", "mayor", "menor", "respecto", "supera", "debajo")
    )
    has_gap = any(marker in text for marker in ("no informa", "no menciona", "falta", "no detalla"))
    multimodal_bonus = 1 if chunk.metadata.get("requires_multimodal") else 0
    
    # NUEVO: Bonus por tamaño del chunk (chunks más grandes = más contexto = mejor)
    size_bonus = min(chunk.token_count // 1000, 5)  # Hasta +5 puntos por chunks grandes
    
    match kind:
        case ExampleKind.EXTRACTIVE:
            return (1 + number_count + multimodal_bonus + size_bonus, chunk.token_count)
        case ExampleKind.INFERENTIAL:
            return (number_count + (2 if has_comparison else 0) + multimodal_bonus + size_bonus, chunk.token_count)
        case ExampleKind.UNANSWERABLE:
            # Para unanswerable, preferimos chunks grandes con contenido variado
            return ((2 if has_gap else 0) + multimodal_bonus + size_bonus * 2, chunk.token_count)
        case ExampleKind.MULTI_CHUNK:
            return (len(chunk.neighbors) + size_bonus, chunk.token_count)
        case ExampleKind.FORMAT_SPECIFIC:
            return ((2 if has_list else 0) + number_count + size_bonus, chunk.token_count)
    return (0, chunk.token_count)


def plan_generation_targets(
    chunks: list[ChunkRecord],
    mix: dict[str, float],
    *,
    targets_per_chunk: int = 1,
) -> list[GenerationTarget]:
    """Planifica targets según mix. ``targets_per_chunk`` multiplica cobertura.

    Con un corpus pequeño (1-5 chunks) y ``targets_per_chunk=3`` se obtienen
    9-15 ejemplos garantizando diversidad de tipos. En corpus grandes (100+)
    la misma proporción escala naturalmente con ``len(chunks)``.
    """
    effective_total = max(1, len(chunks) * max(1, targets_per_chunk))
    counts = _target_kind_counts(effective_total, mix)
    targets: list[GenerationTarget] = []
    remaining_chunks = list(chunks)

    def pick_for_kind(kind: ExampleKind, used: set[str]) -> ChunkRecord:
        eligible = [c for c in remaining_chunks if c.chunk_id not in used]
        if not eligible:
            eligible = list(chunks)
        return max(eligible, key=lambda item: _score_chunk_for_kind(item, kind))

    used_per_kind: dict[ExampleKind, set[str]] = {kind: set() for kind in ExampleKind}
    for kind in [
        ExampleKind.MULTI_CHUNK,
        ExampleKind.INFERENTIAL,
        ExampleKind.UNANSWERABLE,
        ExampleKind.FORMAT_SPECIFIC,
        ExampleKind.EXTRACTIVE,
    ]:
        quota = counts.get(kind, 0)
        for _ in range(quota):
            selected = pick_for_kind(kind, used_per_kind[kind])
            used_per_kind[kind].add(selected.chunk_id)
            targets.append(
                GenerationTarget(primary_chunk_id=selected.chunk_id, requested_kind=kind)
            )
            # Reset del set cuando ya cubrimos todos los chunks: permite repetir
            if len(used_per_kind[kind]) >= len(chunks):
                used_per_kind[kind].clear()

    return targets


def select_pending_chunks(chunks: list[ChunkRecord], existing_examples: list[GeneratedExample]) -> list[ChunkRecord]:
    generated_primary_chunk_ids = {
        example.chunk_ids[0]
        for example in existing_examples
        if example.chunk_ids
    }
    return [chunk for chunk in chunks if chunk.chunk_id not in generated_primary_chunk_ids]


def select_pending_targets(
    targets: list[GenerationTarget],
    existing_examples: list[GeneratedExample],
) -> list[GenerationTarget]:
    """Resume-aware pending selection.

    Antes se usaba *existence check* sobre (chunk, kind), lo que impedía
    generar múltiples ejemplos del mismo tipo para un chunk. Ahora usa un
    conteo por par y devuelve el remanente respecto a targets solicitados.
    """
    existing_counts: dict[tuple[str, str], int] = {}
    for example in existing_examples:
        if not example.chunk_ids:
            continue
        key = (
            example.chunk_ids[0],
            example.requested_kind or normalize_question_type(example.question_type),
        )
        existing_counts[key] = existing_counts.get(key, 0) + 1

    pending: list[GenerationTarget] = []
    seen_counts: dict[tuple[str, str], int] = {}
    for target in targets:
        key = (target.primary_chunk_id, target.requested_kind.value)
        seen_counts[key] = seen_counts.get(key, 0) + 1
        if seen_counts[key] > existing_counts.get(key, 0):
            pending.append(target)
    return pending


def _build_user_parts(prompt_text: str, chunks: list[ChunkRecord], max_pages_per_chunk: int) -> list[dict[str, Any]] | None:
    image_paths: list[str] = []
    for chunk in chunks:
        for raw_path in chunk.metadata.get("page_image_paths", []):
            path = str(raw_path)
            if path not in image_paths and Path(path).exists():
                image_paths.append(path)
    if not image_paths:
        return None
    parts: list[dict[str, Any]] = [{"type": "text", "text": prompt_text}]
    for path in image_paths[: max(1, max_pages_per_chunk)]:
        parts.append({"type": "image_path", "path": path})
    return parts


def _is_placeholder_evidence(item: str) -> bool:
    normalized = item.strip().lower()
    return normalized.startswith("fragmento ") or normalized in {"fragmento", "evidence", "evidencia"}


def _resolve_evidence(response_evidence: list[str], selected_chunks: list[ChunkRecord], *, is_answerable: bool) -> list[str]:
    if not is_answerable:
        return [item for item in response_evidence if item.strip()]
    chunk_texts = [chunk.text.strip() for chunk in selected_chunks if chunk.text.strip()]
    valid_response = [
        item.strip()
        for item in response_evidence
        if item.strip() and not _is_placeholder_evidence(item)
    ]
    merged: list[str] = []
    for item in valid_response + chunk_texts:
        if item and item not in merged:
            merged.append(item)
    return merged


def _matches_requested_kind(example: GeneratedExample, requested_kind: ExampleKind, refusal_text: str) -> bool:
    actual_kind = normalize_question_type(example.question_type)
    if actual_kind != requested_kind.value:
        return False
    if requested_kind == ExampleKind.UNANSWERABLE:
        return (not example.is_answerable) and example.answer.strip() == refusal_text.strip()
    if requested_kind == ExampleKind.MULTI_CHUNK:
        return len(example.chunk_ids) > 1
    return True


def generate_document_summary(
    chunks: list[ChunkRecord],
    backend: StructuredGenerationBackend,
    language: str,
) -> str | None:
    """Genera un resumen del documento completo para contexto."""
    if not chunks:
        return None
    
    try:
        prompt = build_document_summary_prompt(chunks, language=language)
        response = backend.generate_structured(
            system_prompt=prompt.system,
            user_prompt=prompt.user,
            json_schema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "main_topics": {"type": "array", "items": {"type": "string"}},
                    "structure": {"type": "string"},
                },
                "required": ["summary"],
            },
            session_id="document-summary",
        )
        summary = response.get("summary", "")
        topics = response.get("main_topics", [])
        if topics:
            summary += f"\n\nMain topics: {', '.join(topics)}"
        return summary
    except Exception:
        # Si falla, usar un resumen simple
        headings = [", ".join(chunk.section_path) for chunk in chunks[:5]]
        return f"Document structure: {'; '.join(headings)}" if headings else None


def generate_example_for_target(
    *,
    target: GenerationTarget,
    chunk_map: dict[str, ChunkRecord],
    backend: StructuredGenerationBackend,
    mix: dict[str, float],
    prompt_version: str,
    language: str,
    session_id: str,
    teacher_model: str,
    refusal_text: str,
    max_attempts: int,
    max_pages_per_chunk: int,
    doc_summary: str | None = None,
    all_chunks_text: str | None = None,  # Para UNANSWERABLE: texto completo del documento
) -> GeneratedExample:
    del mix
    chunk = chunk_map[target.primary_chunk_id]
    kind = target.requested_kind
    selected_chunks = [chunk]
    
    # Para MULTI_CHUNK, incluir vecinos
    if kind == ExampleKind.MULTI_CHUNK and chunk.neighbors and chunk.neighbors[0] in chunk_map:
        selected_chunks = [chunk, chunk_map[chunk.neighbors[0]]]
    elif kind == ExampleKind.MULTI_CHUNK:
        kind = ExampleKind.INFERENTIAL
    
    # Para UNANSWERABLE, dar visibilidad completa del documento
    effective_doc_summary = doc_summary
    if kind == ExampleKind.UNANSWERABLE and all_chunks_text:
        effective_doc_summary = f"{doc_summary or 'Document overview'}\n\nFULL DOCUMENT CONTEXT:\n{all_chunks_text[:8000]}"  # Primeros 8000 chars

    prompt = build_generation_prompt(
        kind=kind,
        chunks=selected_chunks,
        language=language,
        prompt_version=prompt_version,
        refusal_text=refusal_text,
        doc_summary=effective_doc_summary,
    )
    user_parts = _build_user_parts(prompt.user, selected_chunks, max_pages_per_chunk=max_pages_per_chunk)
    last_example: GeneratedExample | None = None
    for attempt in range(1, max(1, max_attempts) + 1):
        request_kwargs = {
            "system_prompt": prompt.system,
            "user_prompt": prompt.user,
            "json_schema": GENERATION_SCHEMA,
            "session_id": f"{session_id}-{chunk.chunk_id}-attempt-{attempt}",
        }
        if user_parts:
            request_kwargs["user_parts"] = user_parts
        response = _backend_generate_structured(backend, **request_kwargs)
        is_answerable = bool(response.get("is_answerable", True))
        answer = str(response.get("answer", "")).strip()
        if kind == ExampleKind.UNANSWERABLE:
            is_answerable = False
            answer = refusal_text
        elif not is_answerable and not answer:
            answer = refusal_text
        last_example = GeneratedExample(
            example_id=_example_id(str(response.get("question", "")), [item.chunk_id for item in selected_chunks]),
            doc_id=chunk.doc_id,
            source_doc=chunk.source_doc,
            chunk_ids=[item.chunk_id for item in selected_chunks],
            page_range=(selected_chunks[0].page_range[0], selected_chunks[-1].page_range[1]),
            question_type=normalize_question_type(str(response.get("question_type", kind.value))),
            difficulty=str(response.get("difficulty", "medium")),
            language=language,
            is_answerable=is_answerable,
            question=str(response.get("question", "")).strip(),
            answer=answer,
            evidence=_resolve_evidence(
                [str(item).strip() for item in response.get("evidence", []) if str(item).strip()],
                selected_chunks,
                is_answerable=is_answerable,
            ),
            reasoning=response.get("reasoning"),
            supporting_facts=[str(item).strip() for item in response.get("supporting_facts", []) if str(item).strip()],
            prompt_version=prompt_version,
            teacher_model=teacher_model,
            requested_kind=target.requested_kind.value,
            context_image_paths=[part["path"] for part in user_parts or [] if part.get("type") == "image_path"],
            raw_response=response,
        )
        if _matches_requested_kind(last_example, target.requested_kind, refusal_text):
            return last_example
    assert last_example is not None
    return last_example


def generate_examples_for_split(
    *,
    chunks: list[ChunkRecord],
    backend: StructuredGenerationBackend,
    mix: dict[str, float],
    prompt_version: str,
    language: str,
    session_id: str,
    teacher_model: str,
    refusal_text: str,
) -> list[GeneratedExample]:
    examples: list[GeneratedExample] = []
    chunk_map = {chunk.chunk_id: chunk for chunk in chunks}
    
    # Generar resumen del documento para contexto
    doc_summary = generate_document_summary(chunks, backend, language)
    
    # Para UNANSWERABLE, preparar texto completo
    all_chunks_text = "\n\n".join(chunk.text for chunk in chunks)
    
    targets = plan_generation_targets(chunks, mix)
    for target in targets:
        examples.append(
            generate_example_for_target(
                target=target,
                chunk_map=chunk_map,
                backend=backend,
                mix=mix,
                prompt_version=prompt_version,
                language=language,
                session_id=session_id,
                teacher_model=teacher_model,
                refusal_text=refusal_text,
                max_attempts=3,
                max_pages_per_chunk=2,
                doc_summary=doc_summary,
                all_chunks_text=all_chunks_text,
            )
        )
    return examples


def judge_example(
    *,
    example: GeneratedExample,
    backend: StructuredGenerationBackend,
    session_id: str,
    doc_summary: str | None = None,
) -> GeneratedExample:
    prompt = build_judge_prompt(
        question=example.question,
        answer=example.answer,
        evidence=example.evidence,
        language=example.language,
        doc_summary=doc_summary,
    )
    request_kwargs = {
        "system_prompt": prompt.system,
        "user_prompt": prompt.user,
        "json_schema": JUDGE_SCHEMA,
        "session_id": f"{session_id}-{example.example_id}",
    }
    if example.context_image_paths:
        request_kwargs["user_parts"] = [{"type": "text", "text": prompt.user}] + [
            {"type": "image_path", "path": path}
            for path in example.context_image_paths
            if Path(path).exists()
        ]
    response = _backend_generate_structured(backend, **request_kwargs)
    try:
        judge_score = JudgeScore.model_validate(response)
    except Exception:
        # Respuesta del judge fuera de schema: la marcamos con scores neutrales
        # para que el curate pueda rechazarla con razón clara (low_groundedness).
        judge_score = JudgeScore(
            relevance=0.0,
            groundedness=0.0,
            format=0.0,
            difficulty=0.0,
            overall=0.0,
            rationale="judge response did not match schema",
        )
    return example.model_copy(update={"judge_score": judge_score})