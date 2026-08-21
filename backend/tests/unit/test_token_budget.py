from app.core.token_budget import MAX_CONTEXT_CHARS, MAX_CONTEXT_TOKENS, sanitize_context, truncate_to_token_budget


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
