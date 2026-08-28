from app.api.routes.chat import _derive_title


def test_derive_title_keeps_short_content_as_is():
    assert _derive_title("How does auth work?") == "How does auth work?"


def test_derive_title_collapses_whitespace_and_newlines():
    assert _derive_title("How   does\nauth\n\nwork?") == "How does auth work?"


def test_derive_title_truncates_long_content_at_a_word_boundary():
    content = "Can you explain how the background worker processes analysis jobs and reports progress back?"
    title = _derive_title(content)
    assert title.endswith("...")
    assert len(title) <= 63  # 60-char budget + "..."
    assert not title[:-3].endswith(" ")  # trimmed at a word boundary, no trailing space before "..."


def test_derive_title_handles_a_single_long_word_with_no_spaces():
    content = "x" * 100
    title = _derive_title(content)
    assert title == "x" * 60 + "..."
