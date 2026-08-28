import uuid

from app.core.complexity_radar import analyze_complexity
from app.db.models import File


def _file(path: str, content: str) -> File:
    return File(id=uuid.uuid4(), repo_id=uuid.uuid4(), path=path, content=content)


def test_simple_function_has_baseline_complexity_of_one():
    content = "def add(a, b):\n    return a + b\n"
    result = analyze_complexity([_file("math.py", content)])
    assert result["functions_analyzed"] == 1
    [hotspot] = result["hotspots"]
    assert hotspot["function"] == "add"
    assert hotspot["complexity"] == 1


def test_each_branch_keyword_increases_complexity():
    content = (
        "def classify(x):\n"
        "    if x > 0:\n"
        "        return 'positive'\n"
        "    elif x < 0:\n"
        "        return 'negative'\n"
        "    for i in range(x):\n"
        "        pass\n"
        "    return 'zero'\n"
    )
    result = analyze_complexity([_file("classify.py", content)])
    [hotspot] = result["hotspots"]
    # baseline 1 + if + elif + for = 4
    assert hotspot["complexity"] == 4


def test_logical_operators_each_add_a_path():
    content = "function check(a, b, c) {\n  return a && b || c;\n}\n"
    result = analyze_complexity([_file("check.js", content)])
    [hotspot] = result["hotspots"]
    # baseline 1 + && + || = 3
    assert hotspot["complexity"] == 3


def test_python_match_case_counts_each_case_as_a_branch():
    content = (
        "def handle(status):\n"
        "    match status:\n"
        "        case 200:\n"
        "            return 'ok'\n"
        "        case 404:\n"
        "            return 'missing'\n"
        "        case _:\n"
        "            return 'unknown'\n"
    )
    result = analyze_complexity([_file("handle.py", content)])
    [hotspot] = result["hotspots"]
    assert hotspot["complexity"] == 4  # baseline 1 + 3 case branches


def test_hotspots_are_sorted_by_complexity_descending():
    content = (
        "def simple():\n    return 1\n\n"
        "def complex_one(x):\n"
        "    if x:\n"
        "        if x > 1:\n"
        "            if x > 2:\n"
        "                return x\n"
        "    return 0\n"
    )
    result = analyze_complexity([_file("mixed.py", content)])
    assert result["hotspots"][0]["function"] == "complex_one"
    assert result["hotspots"][0]["complexity"] > result["hotspots"][1]["complexity"]


def test_caps_hotspots_at_five_even_with_more_complex_functions():
    functions = "\n\n".join(
        f"def f{i}(x):\n    if x:\n        return {i}\n    return 0" for i in range(8)
    )
    result = analyze_complexity([_file("many.py", functions)])
    assert result["functions_analyzed"] == 8
    assert len(result["hotspots"]) == 5


def test_average_complexity_is_computed_across_all_scanned_functions():
    content = "def a():\n    return 1\n\ndef b(x):\n    if x:\n        return 1\n    return 0\n"
    result = analyze_complexity([_file("avg.py", content)])
    # a=1, b=2 -> average 1.5
    assert result["average_complexity"] == 1.5


def test_skips_unsupported_languages_without_error():
    result = analyze_complexity([_file("main.go", "func main() {}\n")])
    assert result["functions_analyzed"] == 0
    assert result["hotspots"] == []


def test_empty_repo_yields_zero_functions_analyzed():
    result = analyze_complexity([])
    assert result["functions_analyzed"] == 0
    assert result["average_complexity"] == 0.0
    assert result["hotspots"] == []


def test_never_raises_on_a_huge_file():
    huge = "x = 1\n" * 100_000  # comfortably over the char cap, no real functions
    result = analyze_complexity([_file("generated.js", huge)])
    assert result["functions_analyzed"] == 0


def test_maintainability_score_is_bounded_between_zero_and_a_hundred():
    # A large, deeply-branching function should floor at 0, not go negative.
    body_lines = "\n".join(f"    if x{i}:\n        pass" for i in range(80))
    content = f"def deeply_nested(x0):\n{body_lines}\n"
    result = analyze_complexity([_file("nested.py", content)])
    [hotspot] = result["hotspots"]
    assert 0 <= hotspot["maintainability"] <= 100
