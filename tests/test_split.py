from synthetic_ds.models import DocumentRecord
from synthetic_ds.splitter import split_documents


def make_document(doc_id: str, pages: int) -> DocumentRecord:
    return DocumentRecord(
        doc_id=doc_id,
        source_doc=f"{doc_id}.pdf",
        file_path=f"/tmp/{doc_id}.pdf",
        language="es",
        text=" ".join(["texto"] * pages * 20),
        sections=[],
        page_text=["texto " * 20 for _ in range(pages)],
        metadata={},
    )


def test_split_documents_is_done_by_document_id() -> None:
    documents = [
        make_document("doc-a", 10),
        make_document("doc-b", 2),
        make_document("doc-c", 1),
        make_document("doc-d", 1),
    ]

    result = split_documents(documents, eval_ratio=0.25)

    assert set(result.train_doc_ids).isdisjoint(result.eval_doc_ids)
    assert sorted(result.train_doc_ids + result.eval_doc_ids) == ["doc-a", "doc-b", "doc-c", "doc-d"]
    assert len(result.eval_doc_ids) >= 1
    assert result.frozen is True


def test_split_documents_is_deterministic() -> None:
    documents = [make_document(f"doc-{index}", index + 1) for index in range(5)]

    first = split_documents(documents, eval_ratio=0.2)
    second = split_documents(documents, eval_ratio=0.2)

    assert first == second


def test_split_documents_detects_single_document_mode() -> None:
    result = split_documents([make_document("doc-a", 200)])

    assert result.dataset_mode == "single_document"
    assert result.train_doc_ids == ["doc-a"]
    assert result.eval_doc_ids == []
    assert result.has_clean_eval is False
