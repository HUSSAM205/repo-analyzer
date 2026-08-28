"""Deterministic repo-vs-repo comparison -- zero LLM tokens, zero Redis
dependency. Reuses the existing zero-token flagship tools (complexity_radar,
route_explorer, compliance_scanner, module_map) for each side's raw metrics
rather than recomputing them a second way, so a future change to how e.g.
complexity is scored only has to happen in one place.

Deliberately not fronted by response_cache.py's Redis layer like the other
flagship tools: comparing two repos is (a) cheap -- it's the same per-repo
work get_complexity_radar/get_routes/etc. already do, just called twice --
and (b) has a much larger, less repeatable cache-key space (every distinct
pair of repo IDs), so the hit rate would be far lower than the single-repo
tools' "many viewers, same repo" pattern that makes that cache worthwhile.
"""

from app.core.compliance_scanner import run_compliance_scan
from app.core.complexity_radar import analyze_complexity
from app.core.module_map import directory_breakdown
from app.core.route_explorer import extract_routes
from app.db.models import File

_RISK_RANK = {"low": 0, "medium": 1, "high": 2}

DISCLAIMER = (
    "All metrics are computed locally via static analysis (AST parsing, pattern "
    "matching) with no LLM calls -- see each underlying tool's own disclaimer "
    "(complexity, routes, compliance) for what each figure can and can't capture."
)


def _lines_of_code(files: list[File]) -> int:
    # splitlines(), not count("\n") + 1 -- the latter overcounts by one for
    # every file whose content ends in a trailing newline (the overwhelming
    # majority of real source files), since the trailing "\n" doesn't start
    # a new, non-empty line.
    return sum(len(f.content.splitlines()) for f in files if f.content)


def compute_repo_metrics(files: list[File]) -> dict:
    """Fully deterministic -- always succeeds, same as each underlying tool
    it composes (an empty repo just yields all-zero metrics)."""
    complexity = analyze_complexity(files)
    routes = extract_routes(files)
    compliance = run_compliance_scan(files)

    vulnerability_count = (
        len(compliance["secret_findings"])
        + len(compliance["dangerous_pattern_findings"])
        + sum(1 for f in compliance["license_findings"] if f["risk"] in ("medium", "high"))
    )

    return {
        "file_count": len(files),
        "lines_of_code": _lines_of_code(files),
        "average_complexity": complexity["average_complexity"],
        "functions_analyzed": complexity["functions_analyzed"],
        "route_count": len(routes["routes"]),
        "frameworks_detected": routes["frameworks_detected"],
        "vulnerability_count": vulnerability_count,
        "overall_risk": compliance["overall_risk"],
        "module_breakdown": directory_breakdown(files),
    }


def _security_verdict(metrics_a: dict, metrics_b: dict) -> str:
    rank_a = _RISK_RANK[metrics_a["overall_risk"]]
    rank_b = _RISK_RANK[metrics_b["overall_risk"]]

    if rank_a < rank_b:
        return f"Repo A has the stronger security posture -- lower overall risk ({metrics_a['overall_risk']} vs {metrics_b['overall_risk']})."
    if rank_b < rank_a:
        return f"Repo B has the stronger security posture -- lower overall risk ({metrics_b['overall_risk']} vs {metrics_a['overall_risk']})."

    # Same risk tier -- break the tie on raw finding count, which the risk
    # tier itself collapses away (e.g. two "medium" repos can still differ a
    # lot in how many findings actually drove that tier).
    va, vb = metrics_a["vulnerability_count"], metrics_b["vulnerability_count"]
    if va < vb:
        return f"Both repos carry {metrics_a['overall_risk']} overall risk, but Repo A has fewer flagged findings ({va} vs {vb})."
    if vb < va:
        return f"Both repos carry {metrics_a['overall_risk']} overall risk, but Repo B has fewer flagged findings ({vb} vs {va})."
    return f"Both repos have a comparable security posture ({metrics_a['overall_risk']} overall risk, {va} flagged findings each)."


def diff_metrics(metrics_a: dict, metrics_b: dict) -> dict:
    """Every delta is B minus A -- positive means Repo B's figure is higher.
    Left to the caller/UI to decide whether "higher" reads as better or
    worse for a given metric (e.g. more routes is neutral, more
    vulnerabilities is not)."""
    return {
        "file_count_delta": metrics_b["file_count"] - metrics_a["file_count"],
        "lines_of_code_delta": metrics_b["lines_of_code"] - metrics_a["lines_of_code"],
        "average_complexity_delta": round(metrics_b["average_complexity"] - metrics_a["average_complexity"], 1),
        "route_count_delta": metrics_b["route_count"] - metrics_a["route_count"],
        "vulnerability_count_delta": metrics_b["vulnerability_count"] - metrics_a["vulnerability_count"],
    }


def compare_repos(files_a: list[File], files_b: list[File]) -> dict:
    metrics_a = compute_repo_metrics(files_a)
    metrics_b = compute_repo_metrics(files_b)
    return {
        "metrics_a": metrics_a,
        "metrics_b": metrics_b,
        "deltas": diff_metrics(metrics_a, metrics_b),
        "security_verdict": _security_verdict(metrics_a, metrics_b),
        "disclaimer": DISCLAIMER,
    }
