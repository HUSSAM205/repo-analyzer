"""Deterministic license-risk, secret-leak, and dangerous-code-pattern scanning.

Deliberately has no LLM dependency at all, unlike the other flagship tools --
two reasons: (1) a "compliance" tool's output should be reproducible and
audit-defensible, not a model's best guess on a given day, and (2) license
identification in particular is a legally-sensitive claim ("this package is
MIT-licensed") that an LLM can plausibly hallucinate; asserting it only for
packages in a small curated lookup table (falling back to an explicit
"unknown -- verify manually" for everything else) is more honest than a
fluent-sounding guess. This also means this scan can never 503 the way the
LLM-backed tools can -- it always succeeds, so the caller never needs the
"failure isn't cached" contract those tools use.
"""

import re

from app.db.models import File

_MAX_SECRET_FINDINGS = 20
_MAX_LICENSE_FINDINGS = 30

# name -> (license, risk). Risk reflects redistribution/commercial-use
# friction, not code quality: permissive licenses (MIT/BSD/Apache/ISC) are
# "low"; LGPL is "medium" (usable, but has copyleft obligations on
# modification); strong copyleft (GPL/AGPL) is "high" for a typical
# proprietary SaaS use case. This list is intentionally small -- covering
# the packages an LLM-hallucinated guess would most often get right anyway
# is not the point; covering them *correctly and reproducibly* is.
_KNOWN_LICENSES: dict[str, tuple[str, str]] = {
    # JS/TS ecosystem
    "react": ("MIT", "low"), "react-dom": ("MIT", "low"), "next": ("MIT", "low"),
    "express": ("MIT", "low"), "lodash": ("MIT", "low"), "axios": ("MIT", "low"),
    "vue": ("MIT", "low"), "typescript": ("Apache-2.0", "low"), "webpack": ("MIT", "low"),
    "eslint": ("MIT", "low"), "jest": ("MIT", "low"), "tailwindcss": ("MIT", "low"),
    "redux": ("MIT", "low"), "@reduxjs/toolkit": ("MIT", "low"), "vite": ("MIT", "low"),
    "zod": ("MIT", "low"), "prisma": ("Apache-2.0", "low"), "moment": ("MIT", "low"),
    "chalk": ("MIT", "low"), "commander": ("MIT", "low"), "dotenv": ("BSD-2-Clause", "low"),
    "graphql": ("MIT", "low"), "socket.io": ("MIT", "low"), "mongoose": ("MIT", "low"),
    "sequelize": ("MIT", "low"), "framer-motion": ("MIT", "low"), "styled-components": ("MIT", "low"),
    # Python ecosystem
    "flask": ("BSD-3-Clause", "low"), "django": ("BSD-3-Clause", "low"), "fastapi": ("MIT", "low"),
    "requests": ("Apache-2.0", "low"), "numpy": ("BSD-3-Clause", "low"), "pandas": ("BSD-3-Clause", "low"),
    "sqlalchemy": ("MIT", "low"), "pydantic": ("MIT", "low"), "pytest": ("MIT", "low"),
    "uvicorn": ("BSD-3-Clause", "low"), "celery": ("BSD-3-Clause", "low"), "scipy": ("BSD-3-Clause", "low"),
    "scikit-learn": ("BSD-3-Clause", "low"), "boto3": ("Apache-2.0", "low"), "click": ("BSD-3-Clause", "low"),
    "jinja2": ("BSD-3-Clause", "low"), "cryptography": ("Apache-2.0 OR BSD-3-Clause", "low"),
    "pillow": ("HPND", "low"), "gunicorn": ("MIT", "low"), "httpx": ("BSD-3-Clause", "low"),
    "alembic": ("MIT", "low"), "redis": ("MIT", "low"), "psycopg2": ("LGPL-3.0", "medium"),
    "psycopg2-binary": ("LGPL-3.0", "medium"), "pyqt5": ("GPL-3.0", "high"), "mysqlclient": ("GPL-2.0", "high"),
}

_SKIP_SUFFIXES = (
    ".lock", ".min.js", ".min.css", ".map", ".svg", ".png", ".jpg", ".jpeg",
    ".gif", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".pdf", ".zip",
)


# ---------------------------------------------------------------------------
# Secret-leak detection
# ---------------------------------------------------------------------------

def _redact(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


# (pattern_name, compiled regex, group index of the sensitive value to redact)
_SECRET_PATTERNS: list[tuple[str, re.Pattern, int]] = [
    ("AWS Access Key ID", re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), 1),
    (
        "Generic API key assignment",
        re.compile(r"(?i)\b(?:api[_-]?key|apikey|secret[_-]?key)\b\s*[:=]\s*[\"']([A-Za-z0-9_\-]{16,})[\"']"),
        1,
    ),
    ("Private key block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"), 0),
    ("Slack token", re.compile(r"\b(xox[baprs]-[A-Za-z0-9-]{10,})\b"), 1),
    (
        "Hardcoded password assignment",
        re.compile(r"(?i)\bpassword\b\s*[:=]\s*[\"']([^\"'\s]{6,})[\"']"),
        1,
    ),
    (
        "Database connection string with embedded credentials",
        re.compile(r"\b\w+://[^\s:/'\"]+:([^\s@/'\"]{4,})@"),
        1,
    ),
    ("GitHub personal access token", re.compile(r"\b(ghp_[A-Za-z0-9]{30,})\b"), 1),
]

# Placeholder-y values that trip the generic patterns above but are almost
# never a real leaked secret -- e.g. `.env.example` templates, docs, and
# test fixtures. Skipped so this doesn't flood findings with noise.
_PLACEHOLDER_VALUES = {
    "changeme", "your-api-key", "your_api_key", "xxxxxxxx", "placeholder",
    "example", "test", "todo", "fixme", "secret", "password", "your-secret-key",
}


def _is_scannable(path: str) -> bool:
    return not path.lower().endswith(_SKIP_SUFFIXES)


def _scan_file_for_secrets(path: str, content: str) -> list[dict]:
    findings: list[dict] = []
    lines = content.splitlines()
    for line_no, line in enumerate(lines, start=1):
        for pattern_name, pattern, group in _SECRET_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            value = match.group(group) if group else match.group(0)
            if value.lower() in _PLACEHOLDER_VALUES:
                continue
            findings.append({
                "file": path,
                "line": line_no,
                "pattern": pattern_name,
                "preview": _redact(value),
            })
    return findings


def _scan_for_secrets(files: list[File]) -> list[dict]:
    findings: list[dict] = []
    for f in files:
        if not _is_scannable(f.path):
            continue
        findings.extend(_scan_file_for_secrets(f.path, f.content))
        if len(findings) >= _MAX_SECRET_FINDINGS:
            break
    return findings[:_MAX_SECRET_FINDINGS]


# ---------------------------------------------------------------------------
# Dangerous code pattern detection
# ---------------------------------------------------------------------------

_MAX_DANGEROUS_FINDINGS = 25

# (pattern_name, compiled regex, severity, rationale). Line-by-line matching
# like _SECRET_PATTERNS above -- deliberately a short, well-known list
# (RCE-class execution/deserialization sinks and XSS-class DOM sinks) rather
# than a general-purpose linter's worth of rules: each one here is a single
# call/assignment that is almost always worth a second look regardless of
# surrounding context, which keeps the false-positive rate low enough for an
# always-on, no-LLM-judgment scan. Words are boundary-anchored where dynamic
# language keywords could otherwise substring-match a longer, safe
# identifier (e.g. ast.literal_eval, django's execute()).
_DANGEROUS_PATTERNS: list[tuple[str, re.Pattern, str, str]] = [
    (
        "eval()",
        re.compile(r"\beval\s*\("),
        "high",
        "Executes a string as code -- a classic injection vector if any part of the input is attacker-influenced. (Python and JS both use this name.)",
    ),
    (
        "exec()",
        re.compile(r"\bexec\s*\("),
        "high",
        "Executes a string as code, same risk class as eval().",
    ),
    (
        "os.system()",
        re.compile(r"\bos\.system\s*\("),
        "high",
        "Runs a shell command via the OS shell -- vulnerable to shell injection if any part of the command is built from external input.",
    ),
    (
        "subprocess shell=True",
        re.compile(r"\bshell\s*=\s*True\b"),
        "high",
        "Runs the command through a shell rather than exec'ing the binary directly -- shell metacharacters in any interpolated input become executable.",
    ),
    (
        "pickle deserialization",
        re.compile(r"\bpickle\.(?:loads?|Unpickler)\s*\("),
        "high",
        "Unpickling untrusted data can execute arbitrary code -- pickle is not a safe format for anything except your own trusted, internal data.",
    ),
    (
        "yaml.load() without a safe loader",
        re.compile(r"\byaml\.load\s*\((?![^)]*Safe)"),
        "high",
        "yaml.load() without Loader=yaml.SafeLoader can construct arbitrary Python objects from the input -- use yaml.safe_load() instead.",
    ),
    (
        "new Function()",
        re.compile(r"\bnew\s+Function\s*\("),
        "high",
        "Compiles a string into an executable function at runtime -- functionally equivalent to eval() for injection purposes.",
    ),
    (
        "dangerouslySetInnerHTML",
        re.compile(r"\bdangerouslySetInnerHTML\b"),
        "medium",
        "Injects raw HTML into the DOM, bypassing React's own escaping -- an XSS risk if the HTML includes any unsanitized user input.",
    ),
    (
        "innerHTML assignment",
        re.compile(r"\.innerHTML\s*=(?!=)"),
        "medium",
        "Assigns raw HTML to the DOM -- an XSS risk if the value includes any unsanitized user input.",
    ),
]

# File extensions the dangerous-pattern scan applies to -- deliberately
# narrower than secret scanning's skip-list above: these patterns are all
# language keywords/API calls, so scanning non-code files (markdown, JSON,
# config) would only add noise, not real findings.
_CODE_SUFFIXES = (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")


def _scan_file_for_dangerous_patterns(path: str, content: str) -> list[dict]:
    findings: list[dict] = []
    lines = content.splitlines()
    for line_no, line in enumerate(lines, start=1):
        for pattern_name, pattern, severity, rationale in _DANGEROUS_PATTERNS:
            if not pattern.search(line):
                continue
            findings.append({
                "file": path,
                "line": line_no,
                "pattern": pattern_name,
                "severity": severity,
                "rationale": rationale,
                "snippet": line.strip()[:200],
            })
    return findings


def _scan_for_dangerous_patterns(files: list[File]) -> list[dict]:
    findings: list[dict] = []
    for f in files:
        if not f.path.lower().endswith(_CODE_SUFFIXES):
            continue
        findings.extend(_scan_file_for_dangerous_patterns(f.path, f.content))
        if len(findings) >= _MAX_DANGEROUS_FINDINGS:
            break
    return findings[:_MAX_DANGEROUS_FINDINGS]


# ---------------------------------------------------------------------------
# Dependency/license extraction
# ---------------------------------------------------------------------------

_PACKAGE_JSON_DEP_RE = re.compile(r'"([A-Za-z0-9_.@/-]+)"\s*:\s*"[^"]*"')
_REQUIREMENTS_LINE_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*(?:[=<>!~].*)?$")
_PYPROJECT_DEP_RE = re.compile(r'^\s*([A-Za-z0-9_.-]+)\s*=\s*["\']')
# PEP 621 (the modern standard -- what FastAPI's own pyproject.toml uses,
# among many others) declares dependencies as a plain array of requirement
# strings directly under [project], not as Poetry's per-package
# `name = "version"` table entries -- a genuinely different shape, not just
# a formatting variation, so it needs its own extraction path.
_PEP621_DEPENDENCIES_START_RE = re.compile(r"dependencies\s*=\s*\[")
_QUOTED_STRING_RE = re.compile(r'["\']([^"\']+)["\']')
_PACKAGE_NAME_PREFIX_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)")


def _extract_npm_packages(content: str) -> list[str]:
    import json as _json

    try:
        data = _json.loads(content)
    except Exception:
        return []
    names: list[str] = []
    for key in ("dependencies", "devDependencies"):
        deps = data.get(key)
        if isinstance(deps, dict):
            names.extend(deps.keys())
    return names


def _extract_requirements_packages(content: str) -> list[str]:
    names: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            continue
        match = _REQUIREMENTS_LINE_RE.match(stripped)
        if match:
            names.append(match.group(1))
    return names


def _extract_pep621_array_packages(content: str) -> list[str]:
    start_match = _PEP621_DEPENDENCIES_START_RE.search(content)
    if not start_match:
        return []

    # Bracket-depth scan rather than a non-greedy regex up to the next `]`:
    # an extras marker like `"fastapi[all]"` contains its own `[`/`]` pair,
    # which a naive "stop at the first `]`" match would treat as the
    # array's own close and truncate everything after it. Depth tracking
    # handles a nested pair (its own open bumps depth, its own close brings
    # it back down) exactly like any other balanced-bracket scan -- it
    # doesn't need to know these particular brackets sit inside a string.
    depth = 1
    i = start_match.end()
    while i < len(content) and depth > 0:
        if content[i] == "[":
            depth += 1
        elif content[i] == "]":
            depth -= 1
        i += 1
    array_body = content[start_match.end():i - 1]

    names: list[str] = []
    for spec in _QUOTED_STRING_RE.findall(array_body):
        name_match = _PACKAGE_NAME_PREFIX_RE.match(spec.strip())
        if name_match:
            names.append(name_match.group(1))
    return names


def _extract_pyproject_packages(content: str) -> list[str]:
    # Poetry-style `[tool.poetry.dependencies]` table and PEP 621's
    # `dependencies = [...]` array are mutually exclusive in practice, but
    # trying both unconditionally is harmless -- whichever the file doesn't
    # use simply contributes nothing, and _collect_declared_packages already
    # dedupes by name.
    names: list[str] = list(_extract_pep621_array_packages(content))
    in_deps_section = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_deps_section = "dependencies" in stripped.lower()
            continue
        if in_deps_section:
            match = _PYPROJECT_DEP_RE.match(stripped)
            if match and match.group(1).lower() != "python":
                names.append(match.group(1))
    return names


def _collect_declared_packages(files: list[File]) -> list[tuple[str, str]]:
    """Returns (package_name, ecosystem) pairs, deduplicated, in the order
    first encountered, from every recognized manifest file in the repo.
    """
    seen: set[str] = set()
    result: list[tuple[str, str]] = []

    def _add(names: list[str], ecosystem: str) -> None:
        for name in names:
            key = f"{ecosystem}:{name.lower()}"
            if key in seen:
                continue
            seen.add(key)
            result.append((name, ecosystem))

    for f in files:
        name = f.path.rsplit("/", 1)[-1]
        if name == "package.json":
            _add(_extract_npm_packages(f.content), "npm")
        elif name == "requirements.txt":
            _add(_extract_requirements_packages(f.content), "pypi")
        elif name == "pyproject.toml":
            _add(_extract_pyproject_packages(f.content), "pypi")

    return result


def _classify_license(package: str) -> tuple[str, str, str]:
    known = _KNOWN_LICENSES.get(package.lower())
    if known:
        license_name, risk = known
        return license_name, risk, f"Known permissive/standard license for {package}."
    return (
        "Unknown",
        "unknown",
        "Not in the curated lookup table -- verify the license directly on npm/PyPI before redistributing.",
    )


def _scan_licenses(files: list[File]) -> list[dict]:
    packages = _collect_declared_packages(files)[:_MAX_LICENSE_FINDINGS]
    findings: list[dict] = []
    for package, ecosystem in packages:
        license_name, risk, note = _classify_license(package)
        findings.append({
            "package": package,
            "ecosystem": ecosystem,
            "likely_license": license_name,
            "risk": risk,
            "note": note,
        })
    return findings


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_DISCLAIMER = (
    "Secret detection is pattern-based (regex) and license data comes from a "
    "small curated lookup table -- both are a starting point for a manual "
    "review, not a substitute for a dedicated secret scanner or legal/license "
    "audit tool."
)


def run_compliance_scan(files: list[File]) -> dict:
    """Fully deterministic -- always succeeds (an empty repo just yields
    empty findings), so unlike the LLM-backed flagship tools this has no
    failure/None case for the caller to handle.
    """
    secret_findings = _scan_for_secrets(files)
    license_findings = _scan_licenses(files)
    dangerous_pattern_findings = _scan_for_dangerous_patterns(files)

    if (
        secret_findings
        or any(f["severity"] == "high" for f in dangerous_pattern_findings)
        or any(f["risk"] == "high" for f in license_findings)
    ):
        overall_risk = "high"
    elif dangerous_pattern_findings or any(f["risk"] == "medium" for f in license_findings):
        overall_risk = "medium"
    else:
        overall_risk = "low"

    return {
        "overall_risk": overall_risk,
        "license_findings": license_findings,
        "secret_findings": secret_findings,
        "dangerous_pattern_findings": dangerous_pattern_findings,
        "disclaimer": _DISCLAIMER,
    }
