from __future__ import annotations

from synthetic_ds.models import CuratedSummary, SplitManifest
from synthetic_ds.splitter import dataset_mode_aptitude, dataset_mode_label


def build_report_markdown(
    *,
    document_count: int,
    chunk_count: int,
    generated_counts: dict[str, int],
    curated_summaries: dict[str, CuratedSummary],
    manifest: SplitManifest,
) -> str:
    lines = [
        "# synthetic-ds report",
        "",
        f"- Modo: {dataset_mode_label(manifest.dataset_mode)}",
        f"- Documentos: {document_count}",
        f"- Chunks: {chunk_count}",
        f"- Eval limpio por doc_id: {'si' if manifest.has_clean_eval else 'no'}",
        f"- Aptitud: {dataset_mode_aptitude(manifest.dataset_mode)}",
        "",
        "## Generacion",
    ]
    for split, count in generated_counts.items():
        lines.append(f"- {split}: {count}")

    lines.extend(["", "## Curacion"])
    for split, summary in curated_summaries.items():
        lines.append(
            f"- {split}: accepted={summary.accepted} rejected={summary.rejected} total={summary.total_input}"
        )
        for reason, count in summary.rejected_by_reason.items():
            lines.append(f"  - {reason}: {count}")
    return "\n".join(lines)
