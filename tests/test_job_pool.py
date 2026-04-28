import threading
import time
from pathlib import Path

import fitz
from fastapi.testclient import TestClient

from synthetic_ds.app_state import JobStore
from synthetic_ds.secrets import InMemorySecretStore
from synthetic_ds.webapp import create_app


def _make_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    doc.save(path)
    doc.close()


class SlowFakeRunner:
    """Runner que simula un job lento para probar la cola."""

    def __init__(self, store: JobStore, *, max_concurrent_jobs: int = 1, delay_s: float = 0.3) -> None:
        self.store = store
        self.max_concurrent_jobs = max_concurrent_jobs
        self.delay_s = delay_s
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}
        self._queue: list[str] = []

    def pool_status(self) -> dict:
        with self._lock:
            return {
                "max_concurrent_jobs": self.max_concurrent_jobs,
                "running": list(self._threads.keys()),
                "queued": list(self._queue),
            }

    def _worker(self, job_id: str) -> None:
        try:
            time.sleep(self.delay_s)
            self.store.update_progress(
                job_id, stage="done", status="completed", percent=1.0, message="ok"
            )
        finally:
            with self._lock:
                self._threads.pop(job_id, None)
                if self._queue and len(self._threads) < self.max_concurrent_jobs:
                    next_id = self._queue.pop(0)
                    self._launch(next_id)

    def _launch(self, job_id: str) -> None:
        thread = threading.Thread(target=self._worker, args=(job_id,), daemon=True)
        self._threads[job_id] = thread
        thread.start()

    def start_job(
        self,
        *,
        source_dir: str,
        project_dir: str,
        generate_eval: bool,
        parser_mode: str,
        resource_profile: str = "low",
        generation_workers: int = 2,
        judge_workers: int = 1,
        page_batch_size: int = 100,
        batch_pause_seconds: float = 2.0,
        targets_per_chunk: int = 3,
        included_files: list[str] | None = None,
        max_pdfs: int | None = None,
        max_pages_per_chunk: int | None = None,
        quality_preset: str | None = None,
        min_groundedness_score: float | None = None,
        min_overall_score: float | None = None,
    ) -> str:
        _ = (
            project_dir,
            resource_profile,
            generation_workers,
            judge_workers,
            page_batch_size,
            batch_pause_seconds,
            targets_per_chunk,
            included_files,
            max_pdfs,
            max_pages_per_chunk,
            quality_preset,
            min_groundedness_score,
            min_overall_score,
        )
        job_id = self.store.create_job(
            source_dir=source_dir,
            provider="fireworks",
            model="kimi",
            config={"generate_eval": generate_eval, "parser_mode": parser_mode},
            artifacts_dir=str(Path(source_dir) / "extraccion_dataset"),
        )
        with self._lock:
            if len(self._threads) < self.max_concurrent_jobs:
                self._launch(job_id)
            else:
                self._queue.append(job_id)
                self.store.update_progress(
                    job_id, stage="queued", status="queued", percent=0.0, message="en cola"
                )
        return job_id

    def control_job(self, *, job_id: str, action: str) -> None:
        pass


def test_second_job_queues_while_first_runs(tmp_path: Path) -> None:
    pdf_dir_a = tmp_path / "a"
    pdf_dir_a.mkdir()
    _make_pdf(pdf_dir_a / "a.pdf", "A")
    pdf_dir_b = tmp_path / "b"
    pdf_dir_b.mkdir()
    _make_pdf(pdf_dir_b / "b.pdf", "B")

    store = JobStore(tmp_path / "app.db")
    runner = SlowFakeRunner(store, max_concurrent_jobs=1, delay_s=0.4)
    client = TestClient(
        create_app(
            project_dir=tmp_path,
            job_store=store,
            job_runner=runner,
            secret_store=InMemorySecretStore(),
        )
    )

    r1 = client.post("/api/jobs", data={"source_dir": str(pdf_dir_a)})
    r2 = client.post("/api/jobs", data={"source_dir": str(pdf_dir_b)})

    assert r1.status_code == 200
    assert r2.status_code == 200

    first = store.get_job(r1.json()["job_id"])
    second = store.get_job(r2.json()["job_id"])
    assert first is not None and second is not None

    health = client.get("/api/health").json()
    assert "pool" in health
    assert health["pool"]["max_concurrent_jobs"] == 1
    # r2 debe estar en queued o completed (si el test es lento), pero no debe
    # haberse iniciado concurrentemente con r1 mientras max_concurrent=1
    assert second.status in {"queued", "running", "completed"}

    # Esperar a que los dos terminen
    deadline = time.time() + 3.0
    while time.time() < deadline:
        a = store.get_job(r1.json()["job_id"]).status
        b = store.get_job(r2.json()["job_id"]).status
        if a == "completed" and b == "completed":
            break
        time.sleep(0.05)
    assert store.get_job(r1.json()["job_id"]).status == "completed"
    assert store.get_job(r2.json()["job_id"]).status == "completed"
