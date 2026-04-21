"""Detección y marcado de contenido matemático para que el LLM lo preserve.

Estrategia:
    * Texto LaTeX ya delimitado por ``$...$`` / ``$$...$$`` / ``\\(...\\)`` /
      ``\\[...\\]`` se mantiene tal cual.
    * Líneas con densidad alta de símbolos matemáticos unicode (∑, ∫, √, ≤,
      ≥, ≠, →, π, ∞, ∂) se marcan con ``$$ ... $$`` para que el modelo sepa
      que debe tratarlas como expresiones y no parafrasearlas.
    * Líneas con patrones identificables (``f(x) = …``, ``x^2``, ``sum_{i=1}^n``)
      también se envuelven.

Devuelve (texto marcado, cantidad de expresiones detectadas). El conteo se
persiste en ``DocumentRecord.metadata["math_expressions"]`` para que el
reporter lo muestre y los curadores puedan filtrar por densidad matemática.
"""
from __future__ import annotations

import re


UNICODE_MATH = set("∑∏∫∮√∛∜±∓≤≥≠≈≡≜≝∞πτσμλΔΣΠΩ∂∇∈∉⊂⊆⊇⊄∪∩→←↔⇒⇐⇔∀∃∅")

_LATEX_INLINE = re.compile(r"(\$[^$\n]+?\$)")
_LATEX_DISPLAY = re.compile(r"(\$\$[\s\S]+?\$\$)")
_LATEX_PAREN = re.compile(r"(\\\([\s\S]+?\\\))")
_LATEX_BRACKET = re.compile(r"(\\\[[\s\S]+?\\\])")

_EQUATION_LINE = re.compile(
    r"""(?x)
    ^\s*
    (?:[A-Za-z]+\s*\(\s*[A-Za-z0-9,\s]+\s*\)\s*=  |   # f(x, y) =
        [A-Za-z][A-Za-z0-9_]*\s*=.*[+\-*/^] |         # y = mx + b
        .{0,20}\\?\\?[A-Za-z]+\{.*\}.*        |         # \frac{..}{..}
        .*\^\s*[-0-9]                                    # x^2, x^{-1}
    )
    """
)


def _looks_like_math(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    unicode_hits = sum(1 for ch in stripped if ch in UNICODE_MATH)
    if unicode_hits >= 2:
        return True
    if unicode_hits >= 1 and any(ch in stripped for ch in "=+-*/^") and len(stripped) < 160:
        return True
    if _EQUATION_LINE.match(stripped) and len(stripped) < 160:
        return True
    return False


def mark_math(text: str) -> tuple[str, int]:
    """Envuelve expresiones matemáticas detectadas con ``$$...$$``.

    Preserva LaTeX pre-existente. Devuelve ``(texto, cantidad_expresiones)``.
    """
    if not text:
        return text, 0

    count = 0

    # 1. Proteger LaTeX ya presente con placeholders
    protected: list[str] = []

    def stash(match: re.Match) -> str:
        nonlocal count
        protected.append(match.group(0))
        count += 1
        return f"\u0001MATH{len(protected) - 1}\u0002"

    working = _LATEX_DISPLAY.sub(stash, text)
    working = _LATEX_BRACKET.sub(stash, working)
    working = _LATEX_PAREN.sub(stash, working)
    working = _LATEX_INLINE.sub(stash, working)

    # 2. Marcar líneas sospechosas
    out_lines: list[str] = []
    for line in working.splitlines():
        if "\u0001MATH" in line:
            out_lines.append(line)
            continue
        if _looks_like_math(line):
            out_lines.append(f"$$ {line.strip()} $$")
            count += 1
        else:
            out_lines.append(line)
    result = "\n".join(out_lines)

    # 3. Restaurar LaTeX original
    for idx, snippet in enumerate(protected):
        result = result.replace(f"\u0001MATH{idx}\u0002", snippet)

    return result, count


def count_math(text: str) -> int:
    """Variante sin mutación: sólo cuenta expresiones detectadas."""
    _, count = mark_math(text)
    return count
