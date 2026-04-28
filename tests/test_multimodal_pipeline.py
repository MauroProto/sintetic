from pathlib import Path

from synthetic_ds.config import default_config
from synthetic_ds.models import ChunkRecord, DocumentRecord, SplitManifest
from synthetic_ds.pipeline import PipelineSession
from synthetic_ds.storage import build_project_paths, ensure_project_layout, write_json, write_jsonl


class MultimodalFakeBackend:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict,
        session_id: str,
        user_parts=None,
    ) -> dict:
        self.calls.append({"session_id": session_id, "user_parts": user_parts})
        return {
            "question": "Describe la formula principal.",
            "answer": "La formula expresa que energia es igual a masa por velocidad de la luz al cuadrado.",
            "evidence": ["E = mc^2"],
            "reasoning": None,
            "supporting_facts": [],
            "question_type": "extractive",
            "difficulty": "medium",
            "is_answerable": True,
        }


def test_pipeline_session_attaches_page_images_for_multimodal_chunks(tmp_path: Path) -> None:
    run_dir = tmp_path / "PDFs Pepito" / "extraccion_dataset"
    paths = build_project_paths(tmp_path, run_dir=run_dir, work_subdir="job-mm")
    ensure_project_layout(paths)
    config = default_config()
    config.generation.targets_per_chunk = 1

    image_path = paths.artifacts_dir / "pages" / "doc-1" / "page-0001.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"fake-png")

    document = DocumentRecord(
        doc_id="doc-1",
        source_doc="formula.pdf",
        file_path=str(tmp_path / "formula.pdf"),
        language="es",
        text="Formula principal E = mc^2.",
        sections=[],
        page_text=["Formula principal E = mc^2."],
        metadata={"page_count": 1},
    )
    chunk = ChunkRecord(
        chunk_id="chunk-1",
        doc_id="doc-1",
        source_doc="formula.pdf",
        section_path=[],
        page_range=(1, 1),
        text="Formula principal E = mc^2.",
        token_count=5,
        text_hash="hash-1",
        neighbors=[],
        metadata={
            "page_image_paths": [str(image_path)],
            "requires_multimodal": True,
        },
    )
    write_jsonl([document], paths.documents_path)
    write_jsonl([chunk], paths.chunks_path)
    write_json(SplitManifest(train_doc_ids=["doc-1"], eval_doc_ids=[]).model_dump(mode="json"), paths.split_path)

    backend = MultimodalFakeBackend()
    session = PipelineSession(paths=paths, config=config, backend=backend)

    generated_total = session.generate_split("train")

    assert generated_total == 1
    assert backend.calls
    assert backend.calls[0]["user_parts"] is not None
    assert any(part.get("type") in {"image_path", "image_url"} for part in backend.calls[0]["user_parts"])
