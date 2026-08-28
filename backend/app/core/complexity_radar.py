"""Deterministic cyclomatic-complexity and tech-debt hotspot detection --
zero LLM tokens, reusing ast_parser.py's real tree-sitter function
boundaries (already used by the codebase's embedding/chunking pipeline, so
this doesn't introduce any new parsing risk).

Complexity itself is counted via a simple, robust regex over each
function's own extracted source text (branch keywords: if/elif/for/while/
except/catch/case -- "case" also naturally covers Python 3.10+'s
match/case -- plus && and || as each adding an independent path) rather
than a full per-language tree-sitter grammar walk: McCabe's formal
definition operates on a control-flow graph, and correctly identifying
every branch-introducing node type across five different grammars (with
no way to verify obscure node names against a live parser here) risks
silently getting several of them wrong. A keyword count can undercount an
unusual construct that doesn't use one of these keywords, which is an
acceptable trade for a fast, verifiably-correct hotspot finder rather than
an audit-grade metric.

maintainability_score is a simplified heuristic (complexity + function
length only) -- explicitly NOT the real Halstead-volume-based
Maintainability Index formula. Computing genuine Halstead metrics
(distinct/total operator and operand counts) per language is a much
larger undertaking than this tool's scope justifies, and a mislabeled
"real" MI would be a worse, false-precision result than an honestly
simplified proxy.
"""

import re

from app.core.ast_parser import language_for_path, parse_symbols
from app.db.models import File

_MAX_HOTSPOTS = 5
_MAX_FUNCTIONS_SCANNED = 500
# Parsing a pathologically huge single file is wasted work here -- a repo's
# genuine complexity hotspots are essentially never hiding in a generated/
# vendored multi-megabyte file.
_MAX_FILE_CHARS_TO_PARSE = 200_000

_SUPPORTED_LANGUAGES = {"python", "javascript", "typescript", "tsx"}

_DECISION_KEYWORD_RE = re.compile(r"\b(?:if|elif|for|while|except|catch|case)\b")
_LOGICAL_OPERATOR_RE = re.compile(r"&&|\|\|")


def _cyclomatic_complexity(function_body: str) -> int:
    # Starts at 1 (the function's own single "path" through with no
    # branches) -- standard McCabe baseline.
    complexity = 1
    complexity += len(_DECISION_KEYWORD_RE.findall(function_body))
    complexity += len(_LOGICAL_OPERATOR_RE.findall(function_body))
    return complexity


def _maintainability_score(complexity: int, line_count: int) -> int:
    raw = 100 - (complexity * 2) - (line_count / 4)
    return max(0, min(100, round(raw)))


def analyze_complexity(files: list[File]) -> dict:
    """Fully deterministic -- always succeeds (a repo with no
    Python/JS/TS files, or one where every function is trivial, just
    yields an empty hotspot list, not a failure)."""
    hotspots: list[dict] = []
    total_complexity = 0
    function_count = 0

    for f in files:
        language = language_for_path(f.path)
        if language not in _SUPPORTED_LANGUAGES:
            continue
        if len(f.content) > _MAX_FILE_CHARS_TO_PARSE:
            continue
        try:
            symbols = parse_symbols(f.content, language)
        except Exception:
            # Malformed/unparseable source shouldn't fail the whole scan --
            # skip this one file and keep going, same philosophy as
            # compliance_scanner.py's malformed-package.json handling.
            continue

        for symbol in symbols:
            if symbol.node_type != "function":
                continue
            function_count += 1
            line_count = symbol.end_line - symbol.start_line + 1
            complexity = _cyclomatic_complexity(symbol.content)
            total_complexity += complexity
            hotspots.append({
                "file": f.path,
                "function": symbol.name,
                "line": symbol.start_line,
                "complexity": complexity,
                "maintainability": _maintainability_score(complexity, line_count),
                "line_count": line_count,
            })
            if function_count >= _MAX_FUNCTIONS_SCANNED:
                break
        if function_count >= _MAX_FUNCTIONS_SCANNED:
            break

    hotspots.sort(key=lambda h: h["complexity"], reverse=True)

    return {
        "functions_analyzed": function_count,
        "average_complexity": round(total_complexity / function_count, 1) if function_count else 0.0,
        "hotspots": hotspots[:_MAX_HOTSPOTS],
        "disclaimer": (
            "Complexity is a keyword-based approximation of McCabe cyclomatic complexity, and "
            "maintainability_score is a simplified length+complexity heuristic, not the formal "
            "Halstead-based Maintainability Index -- both are a fast way to spot likely hotspots, "
            "not an audit-grade static analysis result."
        ),
    }
