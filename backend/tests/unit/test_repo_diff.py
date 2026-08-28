import uuid

from app.core.repo_diff import compare_repos, compute_repo_metrics, diff_metrics
from app.db.models import File


def _file(path: str, content: str = "x\ny\n") -> File:
    return File(id=uuid.uuid4(), repo_id=uuid.uuid4(), path=path, content=content)


def test_compute_repo_metrics_on_empty_repo_is_all_zero():
    metrics = compute_repo_metrics([])
    assert metrics == {
        "file_count": 0,
        "lines_of_code": 0,
        "average_complexity": 0.0,
        "functions_analyzed": 0,
        "route_count": 0,
        "frameworks_detected": [],
        "vulnerability_count": 0,
        "overall_risk": "low",
        "module_breakdown": {},
    }


def test_compute_repo_metrics_counts_lines_of_code():
    files = [_file("app/a.py", "line1\nline2\nline3\n"), _file("app/b.py", "one line\n")]
    metrics = compute_repo_metrics(files)
    assert metrics["file_count"] == 2
    assert metrics["lines_of_code"] == 4


def test_compute_repo_metrics_counts_fastapi_routes():
    content = '@app.get("/health")\ndef health():\n    return {"ok": True}\n'
    metrics = compute_repo_metrics([_file("main.py", content)])
    assert metrics["route_count"] == 1
    assert metrics["frameworks_detected"] == ["fastapi"]


def test_compute_repo_metrics_counts_secret_findings_as_vulnerabilities():
    content = 'AWS_KEY = "AKIAABCDEFGHIJKLMNOP"\n'
    metrics = compute_repo_metrics([_file("config.py", content)])
    assert metrics["vulnerability_count"] >= 1
    assert metrics["overall_risk"] == "high"


def test_compute_repo_metrics_includes_module_breakdown():
    files = [_file("app/a.py"), _file("app/b.py"), _file("tests/t.py")]
    metrics = compute_repo_metrics(files)
    assert metrics["module_breakdown"] == {"app": 2, "tests": 1}


def test_diff_metrics_is_b_minus_a():
    metrics_a = compute_repo_metrics([_file("a.py", "1\n2\n3\n")])
    metrics_b = compute_repo_metrics([_file("b.py", "1\n"), _file("c.py", "1\n")])
    deltas = diff_metrics(metrics_a, metrics_b)
    assert deltas["file_count_delta"] == 1
    assert deltas["lines_of_code_delta"] == -1


def test_compare_repos_returns_full_shape():
    files_a = [_file("a.py", "1\n2\n")]
    files_b = [_file("b.py", "1\n")]
    result = compare_repos(files_a, files_b)
    assert set(result.keys()) == {"metrics_a", "metrics_b", "deltas", "security_verdict", "disclaimer"}
    assert result["security_verdict"]
    assert result["disclaimer"]


def test_security_verdict_prefers_lower_overall_risk():
    safe_files = [_file("safe.py", "def f():\n    return 1\n")]
    risky_files = [_file("risky.py", 'AWS_KEY = "AKIAABCDEFGHIJKLMNOP"\n')]
    result = compare_repos(safe_files, risky_files)
    assert "Repo A has the stronger security posture" in result["security_verdict"]


def test_security_verdict_is_comparable_when_both_sides_are_equal():
    files_a = [_file("a.py", "def f():\n    return 1\n")]
    files_b = [_file("b.py", "def g():\n    return 2\n")]
    result = compare_repos(files_a, files_b)
    assert "comparable security posture" in result["security_verdict"]
