from pathlib import Path

from synthetic_ds.app_state import JobStore
from synthetic_ds.job_runner import JobRunner
from synthetic_ds.models import ChunkRecord


def make_chunk(chunk_id: str, page_range: tuple[int, int]) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id,
        doc_id="doc-1",
        source_doc="doc.pdf",
        section_path=[],
        page_range=page_range,
        text="contenido",
        token_count=10,
        text_hash=chunk_id,
        neighbors=[],
        metadata={},
    )


def test_chunk_batches_split_large_single_document_by_page_budget(tmp_path: Path) -> None:
    runner = JobRunner(project_dir=tmp_path, job_store=JobStore(tmp_path / "app.db"))
    chunks = [
        make_chunk("c1", (1, 50)),
        make_chunk("c2", (51, 100)),
        make_chunk("c3", (101, 150)),
    ]

    batches = runner._chunk_batches(chunks, {"doc-1"}, page_batch_size=100)

    assert batches == [["c1", "c2"], ["c3"]]


def test_control_job_sets_control_action_in_store(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "app.db")
    runner = JobRunner(project_dir=tmp_path, job_store=store)
    job_id = store.create_job(
        source_dir=str(tmp_path / "pdfs"),
        provider="fireworks",
        model="accounts/fireworks/routers/kimi-k2p5-turbo",
        config={"generate_eval": False, "parser_mode": "auto"},
        artifacts_dir=str(tmp_path / "pdfs" / "extraccion_dataset"),
    )

    runner.control_job(job_id=job_id, action="pause")

    assert store.get_control_action(job_id) == "pause"
