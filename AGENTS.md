# Agent Runbook

This repository is a local-first synthetic corpus generator for PDFs. It is not
an end-to-end model trainer. Agents should control it through the CLI and JSON
outputs, not through the web UI.

## Requirements

- Python 3.12+
- `uv`
- Network access to the selected OpenAI-compatible provider
- A provider key available as an environment variable or stored with
  `synthetic-ds provider set-key --stdin`
- For the full parser path: Python extras `parse` and `semantic`
- For OCR: system `tesseract` installed in the host image

## Non-interactive setup

```bash
uv sync --extra parse --extra semantic --extra dev
uv run synthetic-ds init --project-dir .
uv run synthetic-ds provider use fireworks --project-dir . --json
printf '%s\n' "$FIREWORKS_API_KEY" | uv run synthetic-ds provider set-key fireworks --project-dir . --stdin --json
uv run synthetic-ds doctor --project-dir . --json
uv run synthetic-ds provider test fireworks --project-dir . --json
```

If `doctor` reports missing `docling` but PyMuPDF is present, agents can still
process text PDFs with `--parser-mode fast`. If `doctor` reports missing
`tesseract`, OCR for scanned/low-text pages will not work until the host image
installs it (`apt-get install -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-spa`
on Debian/Ubuntu, or `brew install tesseract tesseract-lang` on macOS).

For other providers, inspect the required env var with:

```bash
uv run synthetic-ds provider list --project-dir . --json
```

## Recommended async job flow

```bash
uv run synthetic-ds submit ./pdfs \
  --project-dir . \
  --parser-mode fast \
  --agent \
  --allow-partial-export \
  --max-pdfs 10 \
  --max-pages-per-chunk 25 \
  --quality-preset strict \
  --min-groundedness-score 0.8 \
  --min-overall-score 0.8 \
  --resource-profile low \
  --generation-workers 2 \
  --judge-workers 1 \
  --targets-per-chunk 3 \
  --json
```

Parse `job_id` from the JSON response, then poll:

```bash
uv run synthetic-ds status --job-id "$JOB_ID" --json
uv run synthetic-ds events --job-id "$JOB_ID" --json
uv run synthetic-ds wait --job-id "$JOB_ID" --timeout-seconds 3600 --json
```

`submit` starts a detached worker. The launcher process may exit; `status`,
`events`, and `wait` keep reading durable job state from the local job store.

## Foreground flow

Use this when the agent wants one blocking command:

```bash
uv run synthetic-ds run ./pdfs \
  --project-dir . \
  --parser-mode fast \
  --agent \
  --max-pdfs 10 \
  --max-pages-per-chunk 25 \
  --quality-preset strict \
  --min-groundedness-score 0.8 \
  --min-overall-score 0.8 \
  --json
```

## Output contract

The public corpus artifacts are written under:

```text
PDF_FOLDER/extraccion_dataset/
```

Important files:

- `train.jsonl`: accepted training examples.
- `eval.jsonl`: clean document-level eval split when the source has multiple PDFs.
- `review_sample.jsonl` and `review_sample.csv`: human audit sample.
- `latest.md`: generation report.

Internal resumable state lives under:

```text
PDF_FOLDER/extraccion_dataset/.work/
```

Agents should not edit `.work/` directly.

Phase checkpoints are written under:

```text
PDF_FOLDER/extraccion_dataset/.work/checkpoints/
```

If a run is interrupted, prefer:

```bash
uv run synthetic-ds run ./pdfs --project-dir . --resume --json
```

If train is already curated and only eval needs judging/exporting:

```bash
uv run synthetic-ds run ./pdfs --project-dir . --from-phase judge_eval --only-eval --allow-partial-export --json
```

`--from-phase judge --only-eval` is accepted as an alias for the same eval-only
recovery path.

## Quality target semantics

`--min-overall-score 0.8` and `--min-groundedness-score 0.8` are corpus quality
gates based on the internal LLM judge. They do not prove that a fine-tuned model
will score `0.8` on an external benchmark. They ensure exported examples passed
the configured judge thresholds.

## PDF and chunk sizing

- `--max-pdfs N` limits how many PDFs/books are selected from a folder. Omit it
  to process every discovered PDF.
- `--include-file relative.pdf` is stricter than `--max-pdfs` when the agent
  knows exactly which PDFs to process.
- `--max-pages-per-chunk N` prevents sparse large books from becoming a single
  huge page-range chunk. The default config is `25`.
- `--page-batch-size N` is not chunk size. It controls generation batches after
  ingestion.
- `parsing.docling_max_pages` skips Docling for books above that page count and
  falls back to PyMuPDF before RAM pressure becomes an OOM.
- `parsing.docling_max_ram_mb` skips Docling when available RAM is below the
  configured guard.

## Safe controls

```bash
uv run synthetic-ds pause --job-id "$JOB_ID" --json
uv run synthetic-ds resume --job-id "$JOB_ID" --json
uv run synthetic-ds cancel --job-id "$JOB_ID" --json
```

## Troubleshooting

- If `provider test` fails, fix network/API key/provider config before launching jobs.
- If `wait` returns `failed`, inspect `events --json` and the job `error` field.
- If no examples are exported with strict thresholds, lower the thresholds or improve
  source PDFs; the exporter intentionally refuses empty train output.
- For single-PDF corpora, the tool exports `train.jsonl` plus review files and does
  not create a serious clean eval split.
