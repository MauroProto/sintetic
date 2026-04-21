from __future__ import annotations

from collections import defaultdict

from synthetic_ds.models import ChunkRecord


def _token_set(text: str) -> set[str]:
    return {token.lower() for token in text.split() if len(token) > 2}


def attach_neighbors(chunks: list[ChunkRecord], max_neighbors: int = 2) -> list[ChunkRecord]:
    grouped: dict[str, list[ChunkRecord]] = defaultdict(list)
    for chunk in chunks:
        grouped[chunk.doc_id].append(chunk)

    indexed: list[ChunkRecord] = []
    for doc_chunks in grouped.values():
        for index, chunk in enumerate(doc_chunks):
            candidates = []
            if index > 0:
                candidates.append(doc_chunks[index - 1])
            if index + 1 < len(doc_chunks):
                candidates.append(doc_chunks[index + 1])
            current_tokens = _token_set(chunk.text)
            for other in doc_chunks:
                if other.chunk_id == chunk.chunk_id or other in candidates:
                    continue
                overlap = len(current_tokens & _token_set(other.text))
                if overlap:
                    candidates.append(other)
            ordered = []
            for candidate in candidates:
                if candidate.chunk_id not in ordered:
                    ordered.append(candidate.chunk_id)
            indexed.append(chunk.model_copy(update={"neighbors": ordered[:max_neighbors]}))
    return indexed
