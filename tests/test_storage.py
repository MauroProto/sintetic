from pathlib import Path

from synthetic_ds.models import GeneratedExample
from synthetic_ds.storage import append_jsonl, build_project_paths, build_run_output_dir, read_jsonl


def test_append_jsonl_persists_incremental_records(tmp_path: Path) -> None:
    path = tmp_path / "items.jsonl"
    item = GeneratedExample(
        example_id="ex-1",
        doc_id="doc-1",
        source_doc="doc.pdf",
        chunk_ids=["chunk-1"],
        page_range=(1, 1),
        question_type="extractive",
        difficulty="low",
        language="es",
        is_answerable=True,
        question="q",
        answer="a",
        evidence=["e"],
        prompt_version="v1",
        teacher_model="model",
        raw_response={},
    )

    append_jsonl(item, path)
    append_jsonl(item.model_copy(update={"example_id": "ex-2", "chunk_ids": ["chunk-2"]}), path)

    loaded = read_jsonl(path, GeneratedExample)

    assert [entry.example_id for entry in loaded] == ["ex-1", "ex-2"]


def test_build_run_output_dir_places_results_inside_source_folder(tmp_path: Path) -> None:
    source_dir = tmp_path / "PDFs Pepito"
    source_dir.mkdir()

    run_dir = build_run_output_dir(source_dir)
    paths = build_project_paths(tmp_path, run_dir=run_dir, work_subdir="job-123")

    assert run_dir == source_dir / "extraccion_dataset"
    assert paths.exports_dir == run_dir
    assert paths.reports_dir == run_dir
    assert paths.artifacts_dir == run_dir / ".work" / "job-123"
