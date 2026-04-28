from synthetic_ds.math_markers import count_math, mark_math


def test_preserves_existing_latex_inline() -> None:
    text = "The formula $E = mc^2$ is famous."
    out, count = mark_math(text)
    assert "$E = mc^2$" in out
    assert count == 1


def test_preserves_display_latex() -> None:
    text = "Lagrangian:\n$$\\mathcal{L} = T - V$$\nend."
    out, count = mark_math(text)
    assert "$$\\mathcal{L} = T - V$$" in out
    assert count == 1


def test_marks_unicode_math_line() -> None:
    text = "Probability:\n∑ p_i = 1 and ∫ f(x) dx = 0\nLa integral anterior."
    out, count = mark_math(text)
    assert "$$" in out
    assert count >= 1


def test_does_not_mark_prose() -> None:
    text = "Este es un párrafo normal sin matemática alguna."
    out, count = mark_math(text)
    assert "$$" not in out
    assert count == 0


def test_count_math_helper() -> None:
    text = "f(x) = x^2 + 2\nMás texto."
    assert count_math(text) >= 1
