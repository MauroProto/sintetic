from __future__ import annotations

import csv
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Iterable, TypeVar

from pydantic import BaseModel

from synthetic_ds.models import ProjectPaths

T = TypeVar("T", bound=BaseModel)

PHASES = [
    "ingest",
    "split",
    "generate_train",
    "judge_train",
    "generate_eval",
    "judge_eval",
    "export",
    "report",
]


def build_run_output_dir(source_path: Path, *, job_id: str | None = None) -> Path:
    source_root = source_path.resolve()
    if source_root.is_file():
        source_root = source_root.parent
    run_root = source_root / "extraccion_dataset"
    return run_root / job_id if job_id else run_root


def build_project_paths(
    project_dir: Path,
    *,
    run_dir: Path | None = None,
    work_subdir: str | None = None,
) -> ProjectPaths:
    resolved_project = project_dir.resolve()
    resolved_run_dir = run_dir.resolve() if run_dir is not None else (resolved_project / "artifacts")
    if run_dir is not None:
        internal_dir = resolved_run_dir / ".work"
        if work_subdir:
            internal_dir = internal_dir / work_subdir
    else:
        internal_dir = resolved_run_dir
    exports_dir = resolved_run_dir if run_dir is not None else internal_dir / "exports"
    reports_dir = resolved_run_dir if run_dir is not None else internal_dir / "reports"
    return ProjectPaths(
        project_dir=resolved_project,
        run_dir=resolved_run_dir,
        config_path=resolved_project / "synthetic-ds.yaml",
        artifacts_dir=internal_dir,
        documents_path=internal_dir / "documents.jsonl",
        chunks_path=internal_dir / "chunks.jsonl",
        split_path=internal_dir / "split.json",
        generated_dir=internal_dir / "generated",
        curated_dir=internal_dir / "curated",
        exports_dir=exports_dir,
        reports_dir=reports_dir,
    )


def ensure_project_layout(paths: ProjectPaths) -> None:
    for path in [
        paths.run_dir,
        paths.artifacts_dir,
        paths.generated_dir,
        paths.curated_dir,
        paths.exports_dir,
        paths.reports_dir,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def write_jsonl(items: Iterable[BaseModel], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(item.model_dump_json())
            handle.write("\n")


def append_jsonl(item: BaseModel, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(item.model_dump_json())
        handle.write("\n")


def read_jsonl(path: Path, model: type[T]) -> list[T]:
    if not path.exists():
        return []
    records: list[T] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            records.append(model.model_validate_json(line))
    return records


def write_json(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_phase_checkpoint(
    work_dir: Path,
    phase: str,
    *,
    output_files: Iterable[Path | str] = (),
    stats: dict | None = None,
) -> Path:
    if phase not in PHASES:
        raise ValueError(f"Unknown checkpoint phase '{phase}'")
    checkpoint_path = work_dir / "checkpoints" / f"{phase}.json"
    payload = {
        "phase": phase,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "output_files": [str(path) for path in output_files],
        "stats": stats or {},
    }
    write_json(payload, checkpoint_path)
    return checkpoint_path


def detect_completed_phases(work_dir: Path) -> list[str]:
    checkpoint_dir = work_dir / "checkpoints"
    if not checkpoint_dir.exists():
        return []
    completed: list[str] = []
    for phase in PHASES:
        payload = read_json(checkpoint_dir / f"{phase}.json")
        if payload.get("phase") == phase:
            completed.append(phase)
    return completed


def write_csv_rows(rows: list[dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
