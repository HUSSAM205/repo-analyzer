import uuid

from app.core.module_map import build_module_map
from app.db.models import File


def _file(path: str) -> File:
    return File(id=uuid.uuid4(), repo_id=uuid.uuid4(), path=path, content="x")


def test_groups_files_by_top_level_directory_with_counts():
    files = [
        _file("app/main.py"),
        _file("app/config.py"),
        _file("tests/test_main.py"),
    ]
    result = build_module_map(files)
    assert 'D0["app/ (2 files)"]' in result["diagram"]
    assert 'D1["tests/ (1 file)"]' in result["diagram"]
    assert result["directory_count"] == 2
    assert result["file_count"] == 3


def test_orders_directories_by_file_count_descending():
    files = [_file("small/a.py")] + [_file(f"big/f{i}.py") for i in range(5)]
    result = build_module_map(files)
    diagram_lines = result["diagram"].splitlines()
    big_line = next(i for i, l in enumerate(diagram_lines) if "big/" in l)
    small_line = next(i for i, l in enumerate(diagram_lines) if "small/" in l)
    assert big_line < small_line


def test_skips_vendored_and_build_directories():
    files = [_file("node_modules/lodash/index.js"), _file("app/main.py")]
    result = build_module_map(files)
    assert "node_modules" not in result["diagram"]
    assert result["directory_count"] == 1


def test_counts_root_level_files_separately():
    files = [_file("README.md"), _file("app/main.py")]
    result = build_module_map(files)
    assert "1 file at root" in result["diagram"]


def test_caps_the_number_of_directory_nodes_shown_for_a_very_wide_repo():
    files = [_file(f"dir{i}/file.py") for i in range(25)]
    result = build_module_map(files)
    assert "more director" in result["diagram"]
    assert result["directory_count"] == 25


def test_empty_repo_still_produces_valid_diagram_syntax():
    result = build_module_map([])
    assert result["diagram"].startswith("flowchart TD")
    assert result["file_count"] == 0


def test_escapes_double_quotes_in_directory_names():
    # Extremely unlikely in a real repo, but the label is interpolated
    # directly into Mermaid's `["..."]` node syntax -- an unescaped quote
    # would break the diagram's syntax outright.
    files = [_file('weird"dir/file.py')]
    result = build_module_map(files)
    assert "weird'dir" in result["diagram"]
