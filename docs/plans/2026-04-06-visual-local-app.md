# Visual Local App Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a local visual app that lets the user select a folder of PDFs, configure a dataset-generation run, watch progress in real time, and export curated datasets while defaulting safely to Fireworks Fire Pass with Kimi K2.5 Turbo.

**Architecture:** Add a local-only FastAPI app on top of the existing Python pipeline. Reuse the current ingest/generate/curate/export/report modules as job steps, persist job state locally in SQLite plus filesystem artifacts, and stream progress to the UI with Server-Sent Events. Use PyMuPDF for fast digital PDFs, add OCR fallback for scanned pages, and keep Kimi K2.5 Turbo focused on generation and judging rather than raw OCR.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, Jinja2 templates, HTMX, SSE, SQLite, PyMuPDF, Docling optional, Tesseract/OCRmyPDF optional fallback, existing `synthetic_ds` modules, Fireworks OpenAI-compatible API.

---

### Task 1: Freeze Product Scope

**Files:**
- Create: `docs/product/visual-app-scope.md`
- Modify: `README.md`
- Test: none

**Step 1: Write the scope doc**

Include:
- Local-only app, not multi-user
- Fireworks/Kimi as the default and recommended provider
- Folder-based ingestion
- Real-time progress
- Resume after app restart
- Export `train.jsonl`, `eval.jsonl`, `review_sample.jsonl`, `review_sample.csv`, report
- No training UI in V1

**Step 2: Add non-goals**

Include:
- No cloud sync
- No multi-tenant auth
- No browser upload of file blobs
- No team collaboration
- No model fine-tuning screen yet

**Step 3: Update README**

Add a short section naming the future `synthetic-ds app` command and the Fire Pass-first workflow.

**Step 4: Commit**

```bash
git add docs/product/visual-app-scope.md README.md
git commit -m "docs: define visual app scope"
```


### Task 2: Add App Dependencies and Entry Point

**Files:**
- Modify: `pyproject.toml`
- Create: `src/synthetic_ds/webapp.py`
- Create: `src/synthetic_ds/web/__init__.py`
- Test: `tests/test_webapp_boot.py`

**Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from synthetic_ds.webapp import create_app


def test_create_app_serves_home() -> None:
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200
    assert "synthetic-ds" in response.text
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_webapp_boot.py -q`
Expected: FAIL because `create_app` does not exist.

**Step 3: Write minimal implementation**

Create a `create_app()` function returning a FastAPI app with a single `/` route and add an executable `synthetic-ds app` CLI entry later.

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_webapp_boot.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add pyproject.toml src/synthetic_ds/webapp.py src/synthetic_ds/web/__init__.py tests/test_webapp_boot.py
git commit -m "feat: add local web app skeleton"
```


### Task 3: Add Persistent Run State

**Files:**
- Create: `src/synthetic_ds/app_state.py`
- Create: `src/synthetic_ds/job_models.py`
- Modify: `src/synthetic_ds/storage.py`
- Test: `tests/test_app_state.py`

**Step 1: Write the failing test**

```python
from pathlib import Path

from synthetic_ds.app_state import JobStore


def test_job_store_persists_runs(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "app.db")
    job_id = store.create_job(source_dir="/tmp/pdfs")
    store.update_progress(job_id, stage="ingest", percent=0.25)

    reloaded = JobStore(tmp_path / "app.db")
    job = reloaded.get_job(job_id)
    assert job.stage == "ingest"
    assert job.percent == 0.25
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_app_state.py -q`
Expected: FAIL because `JobStore` does not exist.

**Step 3: Write minimal implementation**

Use SQLite with one `jobs` table and one `job_events` table.

Columns:
- `job_id`
- `source_dir`
- `provider`
- `status`
- `stage`
- `percent`
- `current_file`
- `message`
- `created_at`
- `updated_at`
- `config_json`
- `artifacts_dir`

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_app_state.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add src/synthetic_ds/app_state.py src/synthetic_ds/job_models.py src/synthetic_ds/storage.py tests/test_app_state.py
git commit -m "feat: persist app jobs in sqlite"
```


### Task 4: Build a Single-Worker Job Runner

**Files:**
- Create: `src/synthetic_ds/job_runner.py`
- Modify: `src/synthetic_ds/cli.py`
- Test: `tests/test_job_runner.py`

**Step 1: Write the failing test**

```python
from synthetic_ds.job_runner import JobRunner


def test_job_runner_executes_steps_in_order(fake_project, fake_backend):
    runner = JobRunner(project_dir=fake_project, backend_factory=lambda *_args, **_kwargs: fake_backend)
    history = runner.run_sync(source_dir=fake_project / "pdfs", generate_eval=False)
    assert history == ["ingest", "split", "generate_train", "curate_train", "export", "report"]
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_job_runner.py -q`
Expected: FAIL because `JobRunner` does not exist.

**Step 3: Write minimal implementation**

Wrap the existing pipeline functions:
- `run_ingest`
- `run_split`
- `run_generate`
- `run_curate`
- `run_export`
- `run_report`

Default behavior:
- one active job at a time
- second job is queued or rejected
- app can resume the last incomplete job

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_job_runner.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add src/synthetic_ds/job_runner.py src/synthetic_ds/cli.py tests/test_job_runner.py
git commit -m "feat: add single-worker pipeline runner"
```


### Task 5: Add PDF Type Detection and OCR Fallback

**Files:**
- Create: `src/synthetic_ds/pdf_analysis.py`
- Modify: `src/synthetic_ds/ingest.py`
- Create: `src/synthetic_ds/ocr.py`
- Test: `tests/test_pdf_analysis.py`

**Step 1: Write the failing test**

```python
from synthetic_ds.pdf_analysis import choose_parse_strategy


def test_choose_parse_strategy_prefers_fast_text_for_digital_pdf() -> None:
    strategy = choose_parse_strategy(
        text_chars=3000,
        image_count=0,
        page_count=5,
        scanned_ratio=0.0,
    )
    assert strategy == "pymupdf"
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_pdf_analysis.py -q`
Expected: FAIL because `choose_parse_strategy` does not exist.

**Step 3: Write minimal implementation**

Decision rules:
- If the PDF already has good extractable text, use `PyMuPDF`
- If text density is low or most pages are image-like, use OCR fallback
- If Docling is installed and the document looks layout-heavy, allow `docling`
- If OCR tools are unavailable, mark the file as `needs_ocr` and show it in the UI instead of failing silently

**Step 4: Do not use Kimi vision as the default OCR path**

Reason:
- OCR should be deterministic and cheap in wall-clock time
- page-by-page LLM OCR is slower
- structured text extraction is easier to normalize locally
- Fire Pass documentation guarantees the router and billing behavior, not a dedicated PDF OCR pipeline

**Step 5: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_pdf_analysis.py -q`
Expected: PASS

**Step 6: Commit**

```bash
git add src/synthetic_ds/pdf_analysis.py src/synthetic_ds/ocr.py src/synthetic_ds/ingest.py tests/test_pdf_analysis.py
git commit -m "feat: add pdf strategy detection with ocr fallback"
```


### Task 6: Build the Local UI Shell

**Files:**
- Create: `src/synthetic_ds/web/templates/base.html`
- Create: `src/synthetic_ds/web/templates/index.html`
- Create: `src/synthetic_ds/web/templates/partials/run_form.html`
- Create: `src/synthetic_ds/web/templates/partials/job_status.html`
- Create: `src/synthetic_ds/web/static/app.css`
- Modify: `src/synthetic_ds/webapp.py`
- Test: `tests/test_web_routes.py`

**Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from synthetic_ds.webapp import create_app


def test_home_shows_run_form() -> None:
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200
    assert "Seleccionar carpeta" in response.text
    assert "Iniciar dataset" in response.text
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_web_routes.py -q`
Expected: FAIL because the form does not exist.

**Step 3: Write minimal implementation**

The home screen should have:
- Provider card showing Fireworks/Kimi active
- Folder selector
- Advanced options accordion
- OCR mode selector
- Generate eval toggle
- Review sample size
- Start button
- Recent runs list

**Step 4: Keep the frontend light**

Use:
- server-rendered HTML
- HTMX for partial updates
- no React
- no Vite
- no Electron

**Step 5: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_web_routes.py -q`
Expected: PASS

**Step 6: Commit**

```bash
git add src/synthetic_ds/web/templates src/synthetic_ds/web/static src/synthetic_ds/webapp.py tests/test_web_routes.py
git commit -m "feat: add lightweight local app ui"
```


### Task 7: Add Native Folder Picker and Fire Pass-First Settings

**Files:**
- Create: `src/synthetic_ds/folder_picker.py`
- Modify: `src/synthetic_ds/webapp.py`
- Modify: `src/synthetic_ds/config.py`
- Test: `tests/test_folder_picker.py`

**Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from synthetic_ds.webapp import create_app


def test_pick_folder_endpoint_returns_path(monkeypatch) -> None:
    monkeypatch.setattr("synthetic_ds.folder_picker.pick_directory", lambda: "/tmp/pdfs")
    client = TestClient(create_app())
    response = client.post("/api/pick-folder")
    assert response.json()["path"] == "/tmp/pdfs"
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_folder_picker.py -q`
Expected: FAIL because picker support does not exist.

**Step 3: Write minimal implementation**

Use `tkinter.filedialog.askdirectory()` behind a thin wrapper.

Behavior:
- default provider locked to `fireworks`
- advanced provider switching hidden behind an explicit “modo experto”
- show the exact Fire Pass router in the UI
- warn before using any non-Fireworks provider

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_folder_picker.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add src/synthetic_ds/folder_picker.py src/synthetic_ds/webapp.py src/synthetic_ds/config.py tests/test_folder_picker.py
git commit -m "feat: add native folder picker and fire pass first settings"
```


### Task 8: Add Real-Time Progress Streaming

**Files:**
- Modify: `src/synthetic_ds/job_runner.py`
- Modify: `src/synthetic_ds/webapp.py`
- Create: `src/synthetic_ds/web/templates/partials/progress_stream.html`
- Test: `tests/test_progress_stream.py`

**Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from synthetic_ds.webapp import create_app


def test_job_status_endpoint_returns_current_stage(fake_job_store) -> None:
    client = TestClient(create_app(job_store=fake_job_store))
    job_id = fake_job_store.create_job(source_dir="/tmp/pdfs")
    fake_job_store.update_progress(job_id, stage="generate_train", percent=0.42)
    response = client.get(f"/api/jobs/{job_id}")
    assert response.json()["stage"] == "generate_train"
    assert response.json()["percent"] == 0.42
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_progress_stream.py -q`
Expected: FAIL because the endpoint does not exist.

**Step 3: Write minimal implementation**

Expose:
- `POST /api/jobs` to create a run
- `GET /api/jobs/{job_id}` for snapshots
- `GET /api/jobs/{job_id}/events` via SSE for live progress

Progress stages:
- `scan_folder`
- `analyze_pdfs`
- `ingest`
- `split`
- `generate_train`
- `judge_train`
- `generate_eval`
- `judge_eval`
- `export`
- `report`
- `done`

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_progress_stream.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add src/synthetic_ds/job_runner.py src/synthetic_ds/webapp.py src/synthetic_ds/web/templates/partials/progress_stream.html tests/test_progress_stream.py
git commit -m "feat: stream job progress to ui"
```


### Task 9: Add Run Review and Artifact Browser

**Files:**
- Create: `src/synthetic_ds/web/templates/run_detail.html`
- Modify: `src/synthetic_ds/webapp.py`
- Test: `tests/test_run_detail.py`

**Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from synthetic_ds.webapp import create_app


def test_run_detail_links_exports(fake_completed_job_store) -> None:
    client = TestClient(create_app(job_store=fake_completed_job_store))
    response = client.get("/runs/job-123")
    assert response.status_code == 200
    assert "train.jsonl" in response.text
    assert "latest.md" in response.text
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_run_detail.py -q`
Expected: FAIL because the page does not exist.

**Step 3: Write minimal implementation**

Show:
- run metadata
- selected folder
- provider/model
- accepted/rejected counts
- rejection reasons
- downloadable artifacts
- top examples from `review_sample.jsonl`

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_run_detail.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add src/synthetic_ds/web/templates/run_detail.html src/synthetic_ds/webapp.py tests/test_run_detail.py
git commit -m "feat: add run detail and artifacts browser"
```


### Task 10: Add Production-Safe Guardrails

**Files:**
- Modify: `src/synthetic_ds/webapp.py`
- Modify: `src/synthetic_ds/job_runner.py`
- Modify: `src/synthetic_ds/cli.py`
- Test: `tests/test_guardrails.py`

**Step 1: Write the failing test**

```python
def test_job_runner_rejects_second_active_job(job_runner, fake_job_store):
    first = fake_job_store.create_job(source_dir="/tmp/a")
    fake_job_store.mark_running(first)
    result = job_runner.try_start(source_dir="/tmp/b")
    assert result.accepted is False
    assert "already running" in result.reason
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_guardrails.py -q`
Expected: FAIL because the guardrail does not exist.

**Step 3: Write minimal implementation**

Guardrails:
- one active job at a time
- explicit cancel button
- resume from last persisted stage
- if API key missing, UI blocks start and shows exact fix
- if provider is not Fireworks, show a billing warning
- skip unchanged PDFs using file hash cache

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_guardrails.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add src/synthetic_ds/webapp.py src/synthetic_ds/job_runner.py src/synthetic_ds/cli.py tests/test_guardrails.py
git commit -m "feat: add app guardrails and resume support"
```


### Task 11: Add App Launch Command and Packaging

**Files:**
- Modify: `src/synthetic_ds/cli.py`
- Modify: `README.md`
- Create: `scripts/run_local_app.sh`
- Test: `tests/test_app_cli.py`

**Step 1: Write the failing test**

```python
from typer.testing import CliRunner

from synthetic_ds.cli import app


def test_app_command_exists() -> None:
    result = CliRunner().invoke(app, ["app", "--help"])
    assert result.exit_code == 0
    assert "local visual app" in result.output.lower()
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_app_cli.py -q`
Expected: FAIL because the command does not exist.

**Step 3: Write minimal implementation**

Add:
- `synthetic-ds app`
- optional `--host`
- optional `--port`
- optional `--open-browser`

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_app_cli.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add src/synthetic_ds/cli.py README.md scripts/run_local_app.sh tests/test_app_cli.py
git commit -m "feat: add app launch command"
```


### Task 12: Full Verification

**Files:**
- Modify: `README.md`
- Test: `tests/test_run_pipeline.py`
- Test: `tests/test_web_routes.py`
- Test: `tests/test_progress_stream.py`

**Step 1: Run the full test suite**

Run: `uv run --extra dev pytest -q`
Expected: all tests pass

**Step 2: Run a local smoke flow**

Run:

```bash
uv run synthetic-ds init --project-dir ./demo-project
uv run synthetic-ds provider use fireworks --project-dir ./demo-project
uv run synthetic-ds provider set-key fireworks --project-dir ./demo-project
uv run synthetic-ds app --project-dir ./demo-project
```

Expected:
- UI opens locally
- folder can be selected
- one run can be started
- status updates stream live
- exports appear when done

**Step 3: Run a Fireworks smoke test**

Use a small PDF folder and verify:
- model is `accounts/fireworks/routers/kimi-k2p5-turbo`
- generation succeeds
- export files are written
- report is visible in UI

**Step 4: Commit**

```bash
git add README.md
git commit -m "test: verify visual app end to end"
```


## Recommended UX

The home screen should be split into two columns:

- Left: run setup
- Right: recent runs and live system status

Run setup should include:
- Selected folder
- Count of discovered PDFs after scan
- Provider badge: `Fireworks Fire Pass`
- Model badge: `Kimi K2.5 Turbo`
- Parser strategy: `Auto / Fast / OCR-safe`
- Generate eval set toggle
- Review sample size
- Start button

Live progress should show:
- current stage
- current file
- docs processed / total
- chunks produced
- generated examples
- accepted vs rejected
- rejection reasons
- elapsed time


## Recommended Parsing Strategy

Default parsing mode should be `Auto`.

Decision tree:
- If the PDF has good text extraction, use `PyMuPDF`
- If the PDF is complex or layout-heavy and Docling is installed, allow `Docling`
- If pages are scanned or text density is too low, use OCR fallback
- Only use remote vision-based extraction as an optional expert mode, not as the default path

This is the low-resource path because:
- most digital PDFs will avoid OCR entirely
- local extraction is much faster than page-by-page model reading
- generation calls are reserved for the dataset stage, where Kimi actually adds value


## Why This Approach

This plan intentionally avoids Electron, React, and always-on background workers because they add complexity and idle memory cost. A local FastAPI app with server-rendered HTML is the easiest way to get:

- a nice visual UI
- live progress
- native folder selection
- minimal machine load
- maximum reuse of the pipeline you already have

If later you want a distributable desktop binary, the exact same app can be wrapped with `pywebview` or `Tauri` without rewriting the backend.
