from synthetic_ds.generate import plan_generation_targets
from synthetic_ds.models import ChunkRecord, ExampleKind


def make_chunk(
    chunk_id: str,
    text: str,
    *,
    neighbors: list[str] | None = None,
) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id,
        doc_id="doc-1",
        source_doc="doc.pdf",
        section_path=[],
        page_range=(1, 1),
        text=text,
        token_count=len(text.split()),
        text_hash=chunk_id,
        neighbors=neighbors or [],
        metadata={},
    )


def test_plan_generation_targets_enforces_real_quota_by_question_type() -> None:
    chunks = [
        make_chunk("c1", "Resumen ejecutivo del documento con contexto general."),
        make_chunk(
            "c2",
            "Resultados Atlas Core obtuvo 669600 dolares y Atlas Labs 223200 dolares con retencion 91.2 y 79.9.",
            neighbors=["c3"],
        ),
        make_chunk("c3", "Comparacion la diferencia de retencion fue de 11.3 puntos porcentuales.", neighbors=["c2"]),
        make_chunk("c4", "Riesgos el documento no informa el costo mensual del proveedor de correo transaccional."),
        make_chunk("c5", "1. Priorizar Atlas Core. 2. Reducir churn. 3. Auditar autenticacion."),
        make_chunk("c6", "Observaciones Atlas Assist mejoro 4.2 puntos respecto del trimestre anterior."),
    ]

    targets = plan_generation_targets(
        chunks=chunks,
        mix={
            "extractive": 0.35,
            "inferential": 0.25,
            "unanswerable": 0.20,
            "multi_chunk": 0.15,
            "format_specific": 0.05,
        },
    )

    counts = {}
    for target in targets:
        counts[target.requested_kind] = counts.get(target.requested_kind, 0) + 1

    assert len(targets) == 6
    assert counts[ExampleKind.EXTRACTIVE] == 2
    assert counts[ExampleKind.INFERENTIAL] == 1
    assert counts[ExampleKind.UNANSWERABLE] == 1
    assert counts[ExampleKind.MULTI_CHUNK] == 1
    assert counts[ExampleKind.FORMAT_SPECIFIC] == 1
