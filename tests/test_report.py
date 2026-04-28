from synthetic_ds.models import CuratedSummary, SplitManifest
from synthetic_ds.reporting import build_report_markdown


def test_build_report_markdown_summarizes_counts() -> None:
    report = build_report_markdown(
        document_count=3,
        chunk_count=12,
        generated_counts={"train": 20, "eval": 5},
        curated_summaries={
            "train": CuratedSummary(total_input=20, accepted=15, rejected=5, rejected_by_reason={"duplicate": 2}),
            "eval": CuratedSummary(total_input=5, accepted=4, rejected=1, rejected_by_reason={"low_groundedness": 1}),
        },
        manifest=SplitManifest(train_doc_ids=["doc-a", "doc-b"], eval_doc_ids=["doc-c"], dataset_mode="multi_document"),
    )

    assert "# synthetic-ds report" in report
    assert "Modo: Multi-document" in report
    assert "Documentos: 3" in report
    assert "Eval limpio por doc_id: si" in report
    assert "train" in report
    assert "duplicate" in report
