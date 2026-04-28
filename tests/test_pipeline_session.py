from pathlib import Path

from synthetic_ds.config import default_config
from synthetic_ds.models import ChunkRecord, DocumentRecord, SplitManifest
from synthetic_ds.pipeline import PipelineSession
from synthetic_ds.storage import build_project_paths, ensure_project_layout, write_json, write_jsonl


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def generate_structured(self, *, system_prompt: str, user_prompt: str, json_schema: dict, session_id: str) -> dict:
        self.calls.append(session_id)
        if "overall" in json_schema.get("properties", {}):
            return {
                "relevance": 0.95,
                "groundedness": 0.92,
                "format": 1.0,
                "difficulty": 0.4,
                "overall": 0.93,
                "rationale": "ok",
            }
        return {
            "question": "Cual es el dato principal?",
            "answer": "El documento describe una prueba controlada.",
            "evidence": ["El documento describe una prueba controlada."],
            "reasoning": None,
            "supporting_facts": [],
            "question_type": "extractive",
            "difficulty": "low",
            "is_answerable": True,
        }


def test_pipeline_session_generates_judges_and_persists_internal_journal(tmp_path: Path) -> None:
    run_dir = tmp_path / "PDFs Pepito" / "extraccion_dataset"
    paths = build_project_paths(tmp_path, run_dir=run_dir, work_subdir="job-1")
    ensure_project_layout(paths)
    config = default_config()
    config.generation.generation_workers = 2
    config.generation.judge_workers = 1
    config.generation.targets_per_chunk = 1

    document = DocumentRecord(
        doc_id="doc-1",
        source_doc="sample.pdf",
        file_path=str(tmp_path / "sample.pdf"),
        language="es",
        text="Resumen\nEl documento describe una prueba controlada.",
        sections=[],
        page_text=["Resumen\nEl documento describe una prueba controlada."],
        metadata={"page_count": 1},
    )
    chunk = ChunkRecord(
        chunk_id="chunk-1",
        doc_id="doc-1",
        source_doc="sample.pdf",
        section_path=[],
        page_range=(1, 1),
        text="El documento describe una prueba controlada.",
        token_count=7,
        text_hash="hash-1",
        neighbors=[],
        metadata={},
    )
    write_jsonl([document], paths.documents_path)
    write_jsonl([chunk], paths.chunks_path)
    write_json(SplitManifest(train_doc_ids=["doc-1"], eval_doc_ids=[]).model_dump(mode="json"), paths.split_path)

    backend = FakeBackend()
    session = PipelineSession(paths=paths, config=config, backend=backend)

    generated_total = session.generate_split("train")
    summary = session.curate_split("train")
    train_count, eval_count, review_count = session.export()

    assert generated_total == 1
    assert summary.accepted == 1
    assert train_count == 1
    assert eval_count == 0
    assert review_count == 1
    assert (paths.artifacts_dir / "judged" / "train.jsonl").exists()
    assert (paths.artifacts_dir / "progress.json").exists()
    assert (paths.exports_dir / "train.jsonl").exists()
    assert not (paths.exports_dir / "eval.jsonl").exists()
    assert len(backend.calls) == 2
