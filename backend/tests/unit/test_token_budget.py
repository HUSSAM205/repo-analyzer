from app.core.token_budget import (
    MAX_CONTEXT_CHARS,
    MAX_CONTEXT_TOKENS,
    extract_outline,
    fits_token_budget,
    sanitize_context,
    truncate_around_match,
    truncate_to_token_budget,
)


def test_sanitize_context_collapses_runs_of_blank_lines():
    text = "line one\n\n\n\n\nline two\n\nline three"
    result = sanitize_context(text)
    assert result == "line one\n\nline two\n\nline three"


def test_sanitize_context_trims_trailing_whitespace_per_line():
    text = "line one   \nline two\t\t\n"
    result = sanitize_context(text)
    assert result == "line one\nline two"


def test_truncate_to_token_budget_leaves_short_text_unchanged():
    text = "a short file\nwith a few lines"
    assert truncate_to_token_budget(text) == text


def test_truncate_to_token_budget_truncates_and_notes_it():
    text = "x" * (MAX_CONTEXT_CHARS * 2)
    result = truncate_to_token_budget(text)

    assert len(result) <= MAX_CONTEXT_CHARS
    assert "truncated" in result
    assert str(MAX_CONTEXT_TOKENS) in result


def test_truncate_to_token_budget_respects_a_custom_budget():
    text = "y" * 1000
    result = truncate_to_token_budget(text, max_tokens=200)

    assert len(result) <= 800  # 200 tokens * 4 chars/token
    assert "truncated" in result


def test_truncate_to_token_budget_handles_a_budget_smaller_than_the_notice_itself():
    # Regression guard: max_chars - len(notice) went negative for a very
    # small max_tokens, and a negative slice index (`sanitized[:-N]`) kept
    # text from the *end* of the string instead of correctly producing an
    # (almost) empty prefix.
    text = "y" * 1000
    result = truncate_to_token_budget(text, max_tokens=1)

    assert not result.startswith("y")
    assert "truncated" in result


def test_truncate_around_match_leaves_short_text_unchanged():
    text = "a short file\nwith pytest mentioned\nand a few more lines"
    assert truncate_around_match(text, "pytest") == text


def test_truncate_around_match_falls_back_to_top_truncation_with_no_query():
    text = "\n".join(f"line {i}" for i in range(2000))
    with_query = truncate_around_match(text, None, max_tokens=50)
    without_query_equivalent = truncate_to_token_budget(text, max_tokens=50)
    assert with_query == without_query_equivalent


def test_truncate_around_match_falls_back_to_top_truncation_when_query_not_found():
    text = "\n".join(f"line {i}" for i in range(2000))
    result = truncate_around_match(text, "nonexistent_needle", max_tokens=50)
    assert result == truncate_to_token_budget(text, max_tokens=50)
    assert result.startswith("line 0")


def test_truncate_around_match_centers_the_window_on_the_matching_line():
    # The real motivating case: a relevant line (e.g. a [tool.pytest]
    # config block) sitting well past where a from-the-top truncation at a
    # tight budget would ever reach.
    lines = [f"filler line {i}" for i in range(1000)]
    lines[700] = "[tool.pytest.ini_options]"
    text = "\n".join(lines)

    top_truncated = truncate_to_token_budget(text, max_tokens=50)
    assert "[tool.pytest.ini_options]" not in top_truncated

    result = truncate_around_match(text, "pytest", max_tokens=50)
    assert "[tool.pytest.ini_options]" in result
    # Doesn't start from the top -- confirms it actually re-centered rather
    # than just returning the same from-the-top slice.
    assert not result.startswith("filler line 0\n")


def test_fits_token_budget_true_for_short_text():
    assert fits_token_budget("a short file") is True


def test_fits_token_budget_false_for_text_over_budget():
    assert fits_token_budget("x" * (MAX_CONTEXT_CHARS + 1)) is False


def test_extract_outline_returns_none_with_no_structural_lines():
    text = "\n".join(f"just some prose line {i}" for i in range(500))
    assert extract_outline(text) is None


def test_extract_outline_finds_toml_section_headers_with_line_numbers():
    lines = ["a = 1"] * 50
    lines[10] = "[build-system]"
    lines[40] = "[tool.pytest.ini_options]"
    text = "\n".join(lines)

    result = extract_outline(text)

    assert result is not None
    assert "   11 | [build-system]" in result
    assert "   41 | [tool.pytest.ini_options]" in result
    # Ordinary "key = value" lines are deliberately not treated as
    # structural -- see extract_outline's docstring for why (in TOML,
    # nearly every line looks like this, so including them wouldn't be an
    # "outline" at all).
    assert "a = 1" not in result


def test_extract_outline_finds_python_def_and_class_lines():
    text = "\n".join([
        "import os",
        "",
        "class Foo:",
        "    def method(self):",
        "        pass",
        "",
        "def standalone():",
        "    pass",
    ])

    result = extract_outline(text)

    assert result is not None
    assert "class Foo:" in result
    assert "def method(self):" in result
    assert "def standalone():" in result
    assert "import os" not in result


def test_extract_outline_omits_entries_past_the_budget():
    lines = [f"[section{i}]" for i in range(200)]
    text = "\n".join(lines)

    result = extract_outline(text, max_tokens=20)

    assert "more outline lines omitted" in result
    assert "[section0]" in result
    assert "[section199]" not in result
