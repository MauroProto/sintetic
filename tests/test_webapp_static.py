import json
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from synthetic_ds.app_state import JobStore
from synthetic_ds.secrets import InMemorySecretStore
from synthetic_ds.webapp import create_app


def _client(tmp_path: Path) -> tuple[TestClient, JobStore]:
    store = JobStore(tmp_path / "app.db")
    client = TestClient(
        create_app(
            project_dir=tmp_path / "project",
            job_store=store,
            secret_store=InMemorySecretStore(),
        )
    )
    return client, store


def test_api_jobs_endpoint_returns_list(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    response = client.get("/api/jobs")
    assert response.status_code == 200
    assert response.json() == []

    store.create_job(
        source_dir=str(tmp_path / "pdfs"),
        provider="fireworks",
        model="accounts/fireworks/routers/kimi-k2p5-turbo",
        config={"generate_eval": False, "parser_mode": "auto"},
        artifacts_dir=str(tmp_path / "pdfs" / "extraccion_dataset"),
    )
    response = client.get("/api/jobs")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["provider"] == "fireworks"


def test_api_providers_exposes_active_profile(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.get("/api/providers")
    assert response.status_code == 200
    payload = response.json()
    assert payload["active"] in payload["profiles"]
    assert "fireworks" in payload["profiles"]
    assert "keys_present" in payload


def test_api_config_roundtrip(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.get("/api/config")
    assert response.status_code == 200
    payload = response.json()
    assert "yaml" in payload
    assert "config" in payload
    original = payload["config"]

    mutated = json.loads(json.dumps(original))
    mutated["chunking"]["target_tokens"] = 777

    save_response = client.post("/api/config", json={"config": mutated})
    assert save_response.status_code == 200
    saved = save_response.json()
    assert saved["config"]["chunking"]["target_tokens"] == 777

    fresh = client.get("/api/config").json()
    assert fresh["config"]["chunking"]["target_tokens"] == 777
    parsed = yaml.safe_load(fresh["yaml"])
    assert parsed["chunking"]["target_tokens"] == 777


def test_api_config_rejects_invalid_yaml(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.post("/api/config", json={"yaml": "invalid: : : :"})
    assert response.status_code == 400


def test_examples_endpoint_reads_curated_jsonl(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    source_dir = tmp_path / "PDFs"
    source_dir.mkdir(parents=True)
    artifacts_dir = source_dir / "extraccion_dataset"
    job_id = store.create_job(
        source_dir=str(source_dir),
        provider="fireworks",
        model="accounts/fireworks/routers/kimi-k2p5-turbo",
        config={"generate_eval": False, "parser_mode": "auto"},
        artifacts_dir=str(artifacts_dir),
    )
    curated_dir = artifacts_dir / ".work" / job_id / "curated"
    curated_dir.mkdir(parents=True)

    example = {
        "example_id": "ex1",
        "doc_id": "doc1",
        "source_doc": "doc1.pdf",
        "chunk_ids": ["c1"],
        "page_range": [1, 2],
        "question_type": "extractive",
        "difficulty": "easy",
        "language": "es",
        "is_answerable": True,
        "question": "\u00bfC\u00f3mo?",
        "answer": "As\u00ed.",
        "evidence": ["ev"],
        "reasoning": None,
        "supporting_facts": [],
        "prompt_version": "v1",
        "teacher_model": "kimi",
        "requested_kind": "extractive",
        "context_image_paths": [],
        "judge_score": {
            "relevance": 0.9,
            "groundedness": 0.95,
            "format": 0.8,
            "difficulty": 0.3,
            "overall": 0.85,
            "rationale": "ok",
        },
        "raw_response": {},
    }
    (curated_dir / "train.jsonl").write_text(
        json.dumps(example, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    rejected = {
        "example": {**example, "example_id": "ex2"},
        "reason": "low_groundedness",
    }
    (curated_dir / "train-rejected.jsonl").write_text(
        json.dumps(rejected, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    response = client.get(f"/api/jobs/{job_id}/examples?split=train&accepted=true")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["example_id"] == "ex1"
    assert payload["items"][0]["accepted"] is True

    response_rejected = client.get(f"/api/jobs/{job_id}/examples?split=train&accepted=false")
    rejected_payload = response_rejected.json()
    assert rejected_payload["items"][0]["accepted"] is False
    assert rejected_payload["items"][0]["reason"] == "low_groundedness"


def test_metrics_endpoint_aggregates_counts(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    source_dir = tmp_path / "PDFs"
    source_dir.mkdir(parents=True)
    artifacts_dir = source_dir / "extraccion_dataset"
    job_id = store.create_job(
        source_dir=str(source_dir),
        provider="fireworks",
        model="accounts/fireworks/routers/kimi-k2p5-turbo",
        config={"generate_eval": False, "parser_mode": "auto"},
        artifacts_dir=str(artifacts_dir),
    )
    work_dir = artifacts_dir / ".work" / job_id
    (work_dir).mkdir(parents=True)
    (work_dir / "progress.json").write_text(
        json.dumps({"accepted": {"train": 3}, "rejected": {"train": 1}}), encoding="utf-8"
    )
    curated_dir = work_dir / "curated"
    curated_dir.mkdir(parents=True)
    (curated_dir / "train-summary.json").write_text(
        json.dumps({"total_input": 4, "accepted": 3, "rejected": 1, "rejected_by_reason": {"duplicate": 1}}),
        encoding="utf-8",
    )

    response = client.get(f"/api/jobs/{job_id}/metrics")
    assert response.status_code == 200
    payload = response.json()
    assert payload["summaries"]["train"]["accepted"] == 3
    assert payload["acceptance"]["train"] == {"accepted": 0, "rejected": 0}


def test_artifact_file_download_respects_path_traversal(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    source_dir = tmp_path / "PDFs"
    source_dir.mkdir()
    artifacts_dir = source_dir / "extraccion_dataset"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "train.jsonl").write_text("hola", encoding="utf-8")
    job_id = store.create_job(
        source_dir=str(source_dir),
        provider="fireworks",
        model="accounts/fireworks/routers/kimi-k2p5-turbo",
        config={"generate_eval": False, "parser_mode": "auto"},
        artifacts_dir=str(artifacts_dir),
    )

    ok = client.get(f"/api/jobs/{job_id}/artifacts/file", params={"path": "train.jsonl"})
    assert ok.status_code == 200
    assert ok.text == "hola"

    bad = client.get(f"/api/jobs/{job_id}/artifacts/file", params={"path": "../../../etc/passwd"})
    assert bad.status_code == 404
