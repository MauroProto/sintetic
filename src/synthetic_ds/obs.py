"""Observabilidad: logging estructurado + helpers de métricas.

Los logs se emiten como líneas JSON por stdout (compatible con structured log
aggregators como jq, vector, fluentbit) y también van a
``~/.cache/synthetic-ds/logs/app.log`` para retención local.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import sys
import time
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Iterator


def _default_log_dir() -> Path:
    home = Path.home()
    if platform.system() == "Darwin":
        return home / "Library" / "Logs" / "synthetic-ds"
    return home / ".cache" / "synthetic-ds" / "logs"


class JsonLineFormatter(logging.Formatter):
    """Formato JSON por línea para consumo en pipelines y jq."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        extras = getattr(record, "extra_fields", None)
        if extras:
            payload.update(extras)
        return json.dumps(payload, ensure_ascii=False, default=str)


_LOGGING_CONFIGURED = False


def configure_logging(*, level: str | int | None = None, log_dir: Path | None = None) -> None:
    """Inicializa logging global idempotente.

    - stderr con nivel INFO (JSON) para observabilidad de consola.
    - archivo rotativo app.log (50MB x 5) con DEBUG para forensics.
    """
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    effective_level = level or os.environ.get("SYNTHETIC_DS_LOG_LEVEL", "INFO")
    if isinstance(effective_level, str):
        effective_level = effective_level.upper()

    root = logging.getLogger("synthetic_ds")
    root.setLevel(logging.DEBUG)
    root.propagate = False
    # Clear cualquier handler previo (repl, tests)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(effective_level if isinstance(effective_level, int) else getattr(logging, effective_level, logging.INFO))
    console.setFormatter(JsonLineFormatter())
    root.addHandler(console)

    try:
        target_dir = log_dir or _default_log_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            target_dir / "app.log",
            maxBytes=50 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(JsonLineFormatter())
        root.addHandler(file_handler)
    except OSError:
        # En entornos sin permisos de filesystem (tests, CI) se omite el archivo
        pass

    _LOGGING_CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Obtiene un logger con prefijo 'synthetic_ds.'."""
    if not name.startswith("synthetic_ds"):
        name = f"synthetic_ds.{name}"
    configure_logging()
    return logging.getLogger(name)


def log_event(logger: logging.Logger, level: int, message: str, **fields: Any) -> None:
    """Helper que añade ``fields`` como extras JSON al log."""
    logger.log(level, message, extra={"extra_fields": fields})


@contextmanager
def timed(logger: logging.Logger, operation: str, **fields: Any) -> Iterator[dict[str, Any]]:
    """Context manager que mide y loggea latencia de la operación."""
    payload: dict[str, Any] = {"op": operation, **fields}
    start = time.perf_counter()
    try:
        yield payload
        elapsed = time.perf_counter() - start
        log_event(logger, logging.INFO, f"{operation} ok", elapsed_ms=round(elapsed * 1000, 1), **payload)
    except Exception as exc:
        elapsed = time.perf_counter() - start
        log_event(
            logger,
            logging.ERROR,
            f"{operation} failed",
            elapsed_ms=round(elapsed * 1000, 1),
            exc_type=type(exc).__name__,
            exc_msg=str(exc)[:500],
            **payload,
        )
        raise


def log_dependency_status() -> dict[str, Any]:
    """Reporta dependencias opcionales detectadas (Tesseract, Docling) y las loggea."""
    logger = get_logger("bootstrap")
    status: dict[str, Any] = {}

    # Tesseract
    import shutil as _shutil
    tesseract = _shutil.which("tesseract")
    status["tesseract"] = {"found": tesseract is not None, "path": tesseract}
    if tesseract:
        log_event(logger, logging.INFO, "tesseract detected", path=tesseract)
    else:
        log_event(
            logger,
            logging.WARNING,
            "tesseract not found - OCR disabled",
            hint="brew install tesseract tesseract-lang (macOS) or apt install tesseract-ocr (Linux)",
        )

    # Docling
    try:
        import docling  # noqa: F401
        status["docling"] = {"found": True}
        log_event(logger, logging.INFO, "docling detected")
    except ImportError:
        status["docling"] = {"found": False}
        log_event(
            logger,
            logging.WARNING,
            "docling not installed - falling back to pymupdf",
            hint="uv sync --extra parse",
        )

    # tiktoken
    try:
        import tiktoken  # noqa: F401
        status["tiktoken"] = {"found": True}
    except ImportError:
        status["tiktoken"] = {"found": False}

    # langdetect
    try:
        import langdetect  # noqa: F401
        status["langdetect"] = {"found": True}
    except ImportError:
        status["langdetect"] = {"found": False}

    return status
