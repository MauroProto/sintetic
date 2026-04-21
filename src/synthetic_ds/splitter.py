from __future__ import annotations

from synthetic_ds.models import DatasetMode, DocumentRecord, SplitManifest


def detect_dataset_mode(document_count: int) -> DatasetMode:
    if document_count == 1:
        return DatasetMode.SINGLE_DOCUMENT
    return DatasetMode.MULTI_DOCUMENT


def dataset_mode_label(mode: DatasetMode | str) -> str:
    normalized = DatasetMode(mode)
    if normalized == DatasetMode.SINGLE_DOCUMENT:
        return "Single-document"
    return "Multi-document"


def dataset_mode_note(mode: DatasetMode | str) -> str:
    normalized = DatasetMode(mode)
    if normalized == DatasetMode.SINGLE_DOCUMENT:
        return "Dataset exportado sin eval limpio por doc_id."
    return "Dataset exportado con eval limpio por doc_id."


def dataset_mode_summary(mode: DatasetMode | str, *, pdf_count: int | None = None) -> str:
    normalized = DatasetMode(mode)
    if normalized == DatasetMode.SINGLE_DOCUMENT:
        prefix = "1 PDF detectado." if pdf_count == 1 else "Corpus single-document detectado."
        return f"{prefix} Se exportara train + review; no hay eval limpio por doc_id."
    if pdf_count is not None:
        return f"{pdf_count} PDFs detectados. Se exportara train + eval + review."
    return "Corpus multi-document detectado. Se exportara train + eval + review."


def dataset_mode_aptitude(mode: DatasetMode | str) -> str:
    normalized = DatasetMode(mode)
    if normalized == DatasetMode.SINGLE_DOCUMENT:
        return "Apto para entrenamiento / no apto como benchmark serio"
    return "Apto para entrenamiento y evaluacion por documento"


def split_documents(documents: list[DocumentRecord], eval_ratio: float = 0.15) -> SplitManifest:
    if not documents:
        return SplitManifest(train_doc_ids=[], eval_doc_ids=[], dataset_mode=DatasetMode.MULTI_DOCUMENT, frozen=True)

    if len(documents) == 1:
        return SplitManifest(
            train_doc_ids=[documents[0].doc_id],
            eval_doc_ids=[],
            dataset_mode=DatasetMode.SINGLE_DOCUMENT,
            frozen=True,
        )

    ordered = sorted(documents, key=lambda item: (item.token_count, item.doc_id), reverse=True)
    total_tokens = sum(max(document.token_count, 1) for document in ordered)
    target_eval_tokens = max(1, int(total_tokens * eval_ratio))

    eval_ids: list[str] = []
    train_ids: list[str] = []
    eval_tokens = 0

    for document in ordered:
        remaining_docs = len(ordered) - (len(eval_ids) + len(train_ids))
        must_keep_for_train = remaining_docs == 1 and not train_ids
        if not must_keep_for_train and (eval_tokens < target_eval_tokens or not eval_ids):
            eval_ids.append(document.doc_id)
            eval_tokens += max(document.token_count, 1)
        else:
            train_ids.append(document.doc_id)

    if not train_ids and eval_ids:
        train_ids.append(eval_ids.pop())

    return SplitManifest(
        train_doc_ids=sorted(train_ids),
        eval_doc_ids=sorted(eval_ids),
        dataset_mode=DatasetMode.MULTI_DOCUMENT,
        frozen=True,
    )
