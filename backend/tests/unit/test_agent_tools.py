from app.core.agent_tools import _MAX_SNIPPET_LINES, _truncate_snippet


def test_truncate_snippet_leaves_short_content_untouched():
    content = "\n".join(f"line {i}" for i in range(10))
    assert _truncate_snippet(content) == content


def test_truncate_snippet_caps_at_max_lines_with_a_marker():
    content = "\n".join(f"line {i}" for i in range(_MAX_SNIPPET_LINES + 15))
    result = _truncate_snippet(content)

    result_lines = result.splitlines()
    # _MAX_SNIPPET_LINES real content lines, plus one appended marker line.
    assert len(result_lines) == _MAX_SNIPPET_LINES + 1
    assert result_lines[:_MAX_SNIPPET_LINES] == [f"line {i}" for i in range(_MAX_SNIPPET_LINES)]
    assert "15 more lines truncated" in result_lines[-1]


def test_truncate_snippet_exactly_at_the_limit_is_untouched():
    content = "\n".join(f"line {i}" for i in range(_MAX_SNIPPET_LINES))
    assert _truncate_snippet(content) == content
