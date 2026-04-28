from pathlib import Path

from synthetic_ds.app_state import JobStore


def test_job_store_persists_progress(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "app.db")

    job_id = store.create_job(
        source_dir="/tmp/pdfs",
        provider="fireworks",
        model="accounts/fireworks/routers/kimi-k2p5-turbo",
        config={"generate_eval": False},
        artifacts_dir="/tmp/project/artifacts",
    )
    store.update_progress(
        job_id,
        stage="ingest",
        status="running",
        percent=0.25,
        current_file="sample.pdf",
        message="Parsing",
    )

    reloaded = JobStore(tmp_path / "app.db")
    job = reloaded.get_job(job_id)

    assert job is not None
    assert job.stage == "ingest"
    assert job.status == "running"
    assert job.percent == 0.25
    assert job.current_file == "sample.pdf"


def test_job_store_persists_stats_and_control_actions(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "app.db")

    job_id = store.create_job(
        source_dir="/tmp/pdfs",
        provider="fireworks",
        model="accounts/fireworks/routers/kimi-k2p5-turbo",
        config={"generate_eval": False},
        artifacts_dir="/tmp/output",
    )
    store.update_progress(
        job_id,
        stage="generate_train",
        status="running",
        percent=0.5,
        message="Batch 1",
        stats={"pages_processed": 100, "requests_completed": 10},
    )
    store.set_control_action(job_id, "pause")

    reloaded = JobStore(tmp_path / "app.db")
    job = reloaded.get_job(job_id)

    assert job is not None
    assert job.stats["pages_processed"] == 100
    assert reloaded.get_control_action(job_id) == "pause"
    reloaded.clear_control_action(job_id)
    assert reloaded.get_control_action(job_id) is None
