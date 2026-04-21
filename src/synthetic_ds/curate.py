from __future__ import annotations

from collections import Counter

from synthetic_ds.generate import normalize_question_type
from synthetic_ds.models import CuratedDataset, CuratedSummary, GeneratedExample, RejectedExample


def _fingerprint(example: GeneratedExample) -> str:
    return f"{example.doc_id}|{example.question.strip().lower()}|{example.answer.strip().lower()}"


def curate_examples(
    examples: list[GeneratedExample],
    *,
    refusal_text: str,
    groundedness_threshold: float,
    overall_threshold: float,
) -> CuratedDataset:
    accepted: list[GeneratedExample] = []
    rejected: list[RejectedExample] = []
    seen: set[str] = set()
    reasons: list[str] = []

    for example in examples:
        fingerprint = _fingerprint(example)
        if fingerprint in seen:
            reasons.append("duplicate")
            rejected.append(RejectedExample(example=example, reason="duplicate"))
            continue

        if example.is_answerable and not example.evidence:
            reasons.append("missing_evidence")
            rejected.append(RejectedExample(example=example, reason="missing_evidence"))
            continue

        if example.requested_kind and normalize_question_type(example.question_type) != example.requested_kind:
            reasons.append("question_type_mismatch")
            rejected.append(RejectedExample(example=example, reason="question_type_mismatch"))
            continue

        if not example.is_answerable and example.answer.strip() != refusal_text.strip():
            reasons.append("invalid_refusal")
            rejected.append(RejectedExample(example=example, reason="invalid_refusal"))
            continue

        if not example.judge_score:
            reasons.append("missing_judge_score")
            rejected.append(RejectedExample(example=example, reason="missing_judge_score"))
            continue

        if example.judge_score.groundedness < groundedness_threshold:
            reasons.append("low_groundedness")
            rejected.append(RejectedExample(example=example, reason="low_groundedness"))
            continue

        if example.judge_score.overall < overall_threshold:
            reasons.append("low_overall")
            rejected.append(RejectedExample(example=example, reason="low_overall"))
            continue

        seen.add(fingerprint)
        accepted.append(example)

    summary = CuratedSummary.from_reasons(
        total_input=len(examples),
        accepted=len(accepted),
        reasons=reasons,
    )
    if not reasons:
        summary = CuratedSummary(
            total_input=len(examples),
            accepted=len(accepted),
            rejected=0,
            rejected_by_reason={},
        )
    return CuratedDataset(accepted=accepted, rejected=rejected, summary=summary)
