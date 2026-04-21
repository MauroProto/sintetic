from __future__ import annotations

import re
from functools import lru_cache

from synthetic_ds.obs import get_logger


WHITESPACE_RE = re.compile(r"\s+")
HYPHEN_RE = re.compile(r"(\w+)-\s*\n\s*(\w+)")


def normalize_text(text: str, repeated_lines: set[str] | None = None) -> str:
    repeated_lines = repeated_lines or set()
    working = HYPHEN_RE.sub(r"\1\2", text)
    lines: list[str] = []
    for raw_line in working.splitlines():
        line = raw_line.strip()
        if not line or line in repeated_lines:
            continue
        lines.append(line)
    normalized = " ".join(lines)
    return WHITESPACE_RE.sub(" ", normalized).strip()


@lru_cache(maxsize=1)
def _get_token_encoding():
    """Carga el encoder BPE perezosamente (tiktoken ``cl100k_base``)."""
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception as exc:  # pragma: no cover
        get_logger("text").warning("tiktoken unavailable, using whitespace estimate (%s)", exc)
        return None


def estimate_tokens(text: str) -> int:
    """Conteo real de tokens (tiktoken). Cae a ``split()`` si tiktoken falla.

    El método previo (whitespace split) subestima sistemáticamente un 20-30%,
    lo que provocaba que algunos chunks excedieran el límite del modelo.
    """
    if not text:
        return 0
    encoding = _get_token_encoding()
    if encoding is None:
        return len(text.strip().split())
    try:
        return len(encoding.encode(text, disallowed_special=()))
    except Exception:  # pragma: no cover
        return len(text.strip().split())


def estimate_image_tokens(width: int, height: int) -> int:
    """Estima tokens de una imagen (heurística OpenAI: ~170 por tile 512x512)."""
    if width <= 0 or height <= 0:
        return 0
    tiles_w = (width + 511) // 512
    tiles_h = (height + 511) // 512
    return 85 + 170 * tiles_w * tiles_h


def detect_language(text: str, *, default: str = "es") -> str:
    """Detecta idioma ISO-639-1 con ``langdetect``. Devuelve ``default`` si falla."""
    if not text or len(text.strip()) < 40:
        return default
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        return detect(text)
    except Exception:
        return default
