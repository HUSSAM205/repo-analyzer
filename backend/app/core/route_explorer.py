"""Deterministic API route extraction (FastAPI, Express, Next.js) -- zero LLM
tokens, same philosophy as compliance_scanner.py: reproducible and always
available regardless of LLM provider quota, rather than an AI guess at "what
are the endpoints" that can hallucinate paths that don't exist.

This is a regex/heuristic scan over source text, not a full parse of each
framework's routing semantics -- deliberately so: a real router can dispatch
dynamically (a path built from a variable, a loop registering routes, a
plugin system), which no static analysis of arbitrary source can resolve in
general. What's covered here is the overwhelmingly common case (a decorator
or method call with a literal string path), which is what the vast majority
of real FastAPI/Express/Next.js route declarations actually look like.

`auth_required` is a heuristic, not a guarantee -- see _looks_auth_guarded's
own docstring for exactly what it checks and why it can be wrong in both
directions (a false "no auth" for a custom/unusual guard pattern, or a false
"auth required" for a `Depends(...)` that isn't actually auth-related).
"""

import re

from app.db.models import File

_MAX_ROUTES = 200

_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head"}

# --- FastAPI ---------------------------------------------------------------

_FASTAPI_ROUTE_RE = re.compile(
    r'@(?:app|router)\.(get|post|put|delete|patch|options|head)\s*\(\s*["\']([^"\']*)["\']',
    re.IGNORECASE,
)
_FASTAPI_ROUTER_PREFIX_RE = re.compile(r'APIRouter\([^)]*prefix\s*=\s*["\']([^"\']*)["\']')
_FASTAPI_PATH_PARAM_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

# --- Express -----------------------------------------------------------

_EXPRESS_ROUTE_RE = re.compile(
    r'\b(?:app|router)\.(get|post|put|delete|patch|options|head|all)\s*\(\s*["\'`]([^"\'`]*)["\'`]',
    re.IGNORECASE,
)
_EXPRESS_PATH_PARAM_RE = re.compile(r":([A-Za-z_][A-Za-z0-9_]*)")

# --- Next.js (App Router: app/**/route.ts, method = exported function name) -

_NEXTJS_METHOD_EXPORT_RE = re.compile(
    r"^\s*export\s+(?:async\s+function|const)\s+(GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)\b",
    re.MULTILINE,
)
_NEXTJS_DYNAMIC_SEGMENT_RE = re.compile(r"\[(\.\.\.)?([A-Za-z_][A-Za-z0-9_]*)\]")

# Words that, found near a route's declaration, suggest it's guarded by some
# auth check -- intentionally broad/generic (covers hand-rolled middleware
# names too, not just this project's own `get_current_user`), at the cost of
# being a heuristic rather than a real guarantee in either direction.
_AUTH_MARKER_RE = re.compile(r"depends\([^)]*(?:auth|user|current_user)|require.?auth|is.?authenticated|verify.?token|auth.?middleware|protect\(", re.IGNORECASE)
_AUTH_LOOKBEHIND_LINES = 4
_AUTH_LOOKAHEAD_LINES = 4


def _looks_auth_guarded(lines: list[str], line_index: int) -> bool:
    """Heuristic only. Checks a small window of lines around the route
    declaration for a recognizable auth-dependency/middleware name -- e.g.
    FastAPI's `current_user: User = Depends(get_current_user)` typically
    appears a line or two below the decorator (in the function signature),
    while an Express auth middleware typically appears as an extra argument
    on the same route-registration line, or immediately above it. Can't see
    a auth check performed *inside* the handler body (e.g. a manual
    `if not request.user: raise ...`), and can produce a false positive for
    a `Depends(...)` whose name happens to contain "user" but isn't actually
    an auth check (e.g. a `get_user_preferences` dependency).
    """
    start = max(0, line_index - _AUTH_LOOKBEHIND_LINES)
    end = min(len(lines), line_index + _AUTH_LOOKAHEAD_LINES + 1)
    window = "\n".join(lines[start:end])
    return bool(_AUTH_MARKER_RE.search(window))


def _extract_fastapi_routes(path: str, content: str) -> list[dict]:
    prefix_match = _FASTAPI_ROUTER_PREFIX_RE.search(content)
    prefix = prefix_match.group(1).rstrip("/") if prefix_match else ""

    lines = content.splitlines()
    routes: list[dict] = []
    for i, line in enumerate(lines):
        match = _FASTAPI_ROUTE_RE.search(line)
        if not match:
            continue
        method, route_path = match.groups()
        full_path = (prefix + route_path) if route_path.startswith("/") else (prefix + "/" + route_path)
        routes.append({
            "method": method.upper(),
            "path": full_path or "/",
            "file": path,
            "line": i + 1,
            "framework": "fastapi",
            "path_params": _FASTAPI_PATH_PARAM_RE.findall(full_path),
            "auth_required": _looks_auth_guarded(lines, i),
        })
    return routes


def _extract_express_routes(path: str, content: str) -> list[dict]:
    lines = content.splitlines()
    routes: list[dict] = []
    for i, line in enumerate(lines):
        match = _EXPRESS_ROUTE_RE.search(line)
        if not match:
            continue
        method, route_path = match.groups()
        if method.lower() not in _HTTP_METHODS and method.lower() != "all":
            continue
        routes.append({
            "method": method.upper(),
            "path": route_path or "/",
            "file": path,
            "line": i + 1,
            "framework": "express",
            "path_params": _EXPRESS_PATH_PARAM_RE.findall(route_path),
            "auth_required": _looks_auth_guarded(lines, i),
        })
    return routes


def _nextjs_route_path_from_file_path(file_path: str) -> str | None:
    # App Router convention: a route lives at app/**/route.ts (or under
    # src/app/), and the URL is that directory path with route-group
    # segments `(name)` dropped and dynamic segments `[slug]`/`[...slug]`
    # converted to `{slug}`/`{...slug}` (matching this tool's FastAPI-style
    # `{param}` convention elsewhere, rather than Next's own bracket syntax).
    normalized = file_path.replace("\\", "/")
    marker = "app/"
    idx = normalized.rfind(marker)
    if idx == -1 or not normalized.endswith(("/route.ts", "/route.js", "/route.tsx")):
        return None
    route_dir = normalized[idx + len(marker):].rsplit("/", 1)[0]
    segments = [s for s in route_dir.split("/") if s and not (s.startswith("(") and s.endswith(")"))]
    url_segments = [_NEXTJS_DYNAMIC_SEGMENT_RE.sub(lambda m: "{" + (m.group(1) or "") + m.group(2) + "}", s) for s in segments]
    # `segments` already includes "api" as a real folder name when the file
    # is genuinely under app/api/... (the overwhelmingly common location for
    # an actual API route.ts, though App Router technically allows a
    # route.ts anywhere under app/) -- prepending it again here would double
    # it up into "/api/api/...".
    return "/" + "/".join(url_segments) if url_segments else "/"


def _extract_nextjs_routes(path: str, content: str) -> list[dict]:
    route_path = _nextjs_route_path_from_file_path(path)
    if route_path is None:
        return []

    lines = content.splitlines()
    routes: list[dict] = []
    for i, line in enumerate(lines):
        match = _NEXTJS_METHOD_EXPORT_RE.match(line)
        if not match:
            continue
        method = match.group(1)
        routes.append({
            "method": method,
            "path": route_path,
            "file": path,
            "line": i + 1,
            "framework": "nextjs",
            "path_params": _FASTAPI_PATH_PARAM_RE.findall(route_path),
            "auth_required": _looks_auth_guarded(lines, i),
        })
    return routes


_DISCLAIMER = (
    "Routes are extracted via pattern matching over literal decorator/method-call paths "
    "(FastAPI, Express) and file-based routing conventions (Next.js App Router) -- a route "
    "built dynamically at runtime won't be found, and auth_required is a heuristic based on "
    "nearby dependency/middleware names, not a guarantee."
)


def extract_routes(files: list[File]) -> dict:
    """Fully deterministic -- always succeeds (a repo with no matching
    framework just yields an empty route list)."""
    routes: list[dict] = []
    for f in files:
        lower = f.path.lower()
        if lower.endswith(".py"):
            routes.extend(_extract_fastapi_routes(f.path, f.content))
        elif lower.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")):
            routes.extend(_extract_express_routes(f.path, f.content))
            routes.extend(_extract_nextjs_routes(f.path, f.content))
        if len(routes) >= _MAX_ROUTES:
            break

    routes = routes[:_MAX_ROUTES]
    frameworks = sorted({r["framework"] for r in routes})
    return {
        "routes": routes,
        "frameworks_detected": frameworks,
        "disclaimer": _DISCLAIMER,
    }
