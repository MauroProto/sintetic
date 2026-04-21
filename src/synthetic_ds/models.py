from __future__ import annotations

from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ExampleKind(StrEnum):
    EXTRACTIVE = "extractive"
    INFERENTIAL = "inferential"
    UNANSWERABLE = "unanswerable"
    MULTI_CHUNK = "multi_chunk"
    FORMAT_SPECIFIC = "format_specific"


class DatasetMode(StrEnum):
    SINGLE_DOCUMENT = "single_document"
    MULTI_DOCUMENT = "multi_document"


class PromptParts(BaseModel):
    system: str
    user: str


class DocumentSection(BaseModel):
    heading: str
    text: str
    page_start: int
    page_end: int


class DocumentRecord(BaseModel):
    doc_id: str
    source_doc: str
    file_path: str
    language: str
    text: str
    sections: list[DocumentSection | dict[str, Any]] = Field(default_factory=list)
    page_text: list[str] = Field(default_factory=list)
    page_assets: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def token_count(self) -> int:
        return len(self.text.split())


class ChunkRecord(BaseModel):
    chunk_id: str
    doc_id: str
    source_doc: str
    section_path: list[str] = Field(default_factory=list)
    page_range: tuple[int, int]
    text: str
    token_count: int
    text_hash: str
    neighbors: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GenerationTarget(BaseModel):
    primary_chunk_id: str
    requested_kind: ExampleKind


class SplitManifest(BaseModel):
    train_doc_ids: list[str]
    eval_doc_ids: list[str]
    dataset_mode: DatasetMode = DatasetMode.MULTI_DOCUMENT
    frozen: bool = True

    @model_validator(mode="before")
    @classmethod
    def _infer_dataset_mode(cls, data: object) -> object:
        if isinstance(data, cls):
            return data
        payload = dict(data or {})
        if payload.get("dataset_mode"):
            return payload
        train_ids = list(payload.get("train_doc_ids", []))
        eval_ids = list(payload.get("eval_doc_ids", []))
        total_doc_ids = len(set(train_ids + eval_ids))
        if total_doc_ids == 1:
            payload["dataset_mode"] = DatasetMode.SINGLE_DOCUMENT
        else:
            payload["dataset_mode"] = DatasetMode.MULTI_DOCUMENT
        return payload

    @property
    def has_clean_eval(self) -> bool:
        return self.dataset_mode == DatasetMode.MULTI_DOCUMENT and bool(self.eval_doc_ids)


class JudgeScore(BaseModel):
    relevance: float
    groundedness: float
    format: float
    difficulty: float
    overall: float
    rationale: str


class GeneratedExample(BaseModel):
    example_id: str
    doc_id: str
    source_doc: str
    chunk_ids: list[str]
    page_range: tuple[int, int]
    question_type: str
    difficulty: str
    language: str
    is_answerable: bool
    question: str
    answer: str
    evidence: list[str] = Field(default_factory=list)
    reasoning: str | None = None
    supporting_facts: list[str] = Field(default_factory=list)
    prompt_version: str
    teacher_model: str
    requested_kind: str | None = None
    context_image_paths: list[str] = Field(default_factory=list)
    judge_score: JudgeScore | None = None
    raw_response: dict[str, Any] = Field(default_factory=dict)


class RejectedExample(BaseModel):
    example: GeneratedExample
    reason: str


class CuratedSummary(BaseModel):
    total_input: int
    accepted: int
    rejected: int
    rejected_by_reason: dict[str, int]

    @classmethod
    def from_reasons(cls, total_input: int, accepted: int, reasons: list[str]) -> "CuratedSummary":
        counter = Counter(reasons)
        return cls(
            total_input=total_input,
            accepted=accepted,
            rejected=sum(counter.values()),
            rejected_by_reason=dict(counter),
        )


class CuratedDataset(BaseModel):
    accepted: list[GeneratedExample] = Field(default_factory=list)
    rejected: list[RejectedExample] = Field(default_factory=list)
    summary: CuratedSummary


class ChatMessage(BaseModel):
    role: str
    content: str


class TrainingRecord(BaseModel):
    messages: list[ChatMessage]
    metadata: dict[str, Any]


class ReviewItem(BaseModel):
    example_id: str
    split: str
    question_type: str
    quality_score: float
    question: str
    answer: str
    source_doc: str
    page_range: tuple[int, int]


class IngestResult(BaseModel):
    documents: list[DocumentRecord] = Field(default_factory=list)
    chunks: list[ChunkRecord] = Field(default_factory=list)


class ProjectPaths(BaseModel):
    project_dir: Path
    run_dir: Path
    config_path: Path
    artifacts_dir: Path
    documents_path: Path
    chunks_path: Path
    split_path: Path
    generated_dir: Path
    curated_dir: Path
    exports_dir: Path
    reports_dir: Path

    model_config = {"arbitrary_types_allowed": True}
