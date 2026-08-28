"""Shared token-budget utilities for capping repository content sent to LLMs.

Provider per-minute token limits are hit fastest by large repository
content -- a full file via read_file, several search_code snippets, or a
whole file's worth of code blocks batched into one annotation prompt.
Confirmed live: a single annotation prompt for a ~1400-line file hit Groq's
"Request too large ... tokens per minute (TPM): Limit 8000, Requested
10426" 413 -- this budget exists to keep any one piece of repository
content comfortably under that kind of limit.

A rough, standard ~4-characters-per-token approximation is used throughout
(good enough to stay well clear of a limit measured in thousands of tokens;
not intended for precise accounting -- getting an exact tokenizer per
provider would be real complexity for no practical benefit here).
"""

import re

# Condensed from 4000: every LLM-facing payload that reuses this shared
# budget (read_file/search_code tool results, code-annotation blocks,
# domain-briefing/doc-generator/security-scanner/health-score prompts) now
# stays comfortably under a 3,500-token ceiling, tightening the margin
# against Groq's per-minute token limit without needing a separate cap per
# caller.
MAX_CONTEXT_TOKENS = 3400
_CHARS_PER_TOKEN = 4
MAX_CONTEXT_CHARS = MAX_CONTEXT_TOKENS * _CHARS_PER_TOKEN


def sanitize_context(text: str) -> str:
    """Strip low-value filler before budgeting.

    Collapses runs of 2+ consecutive blank lines down to 1 and trims
    trailing whitespace from every line, so the token budget is spent on
    real content instead of formatting noise (common in generated/minified
    output and files with heavy vertical whitespace).
    """
    collapsed: list[str] = []
    blank_run = 0
    for line in text.splitlines():
        stripped = line.rstrip()
        if stripped == "":
            blank_run += 1
            if blank_run > 1:
                continue
        else:
            blank_run = 0
        collapsed.append(stripped)
    return "\n".join(collapsed)


def estimate_tokens(text: str) -> int:
    """Rough token-count estimate for `text`, using the same ~4-chars-per-token
    approximation as the rest of this module. Used to budget an aggregate
    prompt (e.g. chat's rolling message history) rather than a single piece
    of content -- see chat.py's _trim_to_token_budget.
    """
    return len(text) // _CHARS_PER_TOKEN


def fits_token_budget(text: str, max_tokens: int = MAX_CONTEXT_TOKENS) -> bool:
    """Whether `text` (after sanitizing) already fits within `max_tokens` --
    i.e. whether truncating it would actually change anything. Used by
    read_file's no-query fallback (see agent_tools.py) to decide whether an
    outline is even worth trying, not just by truncate_to_token_budget's
    own early-return below.
    """
    return len(sanitize_context(text)) <= max_tokens * _CHARS_PER_TOKEN


def truncate_to_token_budget(text: str, max_tokens: int = MAX_CONTEXT_TOKENS) -> str:
    """Sanitize `text` and truncate it to roughly `max_tokens` tokens.

    Returns the text unchanged (aside from sanitizing) if it already fits.
    """
    sanitized = sanitize_context(text)
    max_chars = max_tokens * _CHARS_PER_TOKEN
    if len(sanitized) <= max_chars:
        return sanitized

    notice = f"\n... [truncated to stay within the {max_tokens}-token context budget]"
    # For a very small max_tokens, the notice itself can be longer than
    # max_chars -- clamp to 0 rather than let a negative slice index wrap
    # around and keep text from the *end* of `sanitized` instead of the
    # start.
    keep_chars = max(max_chars - len(notice), 0)
    return sanitized[:keep_chars] + notice


def truncate_around_match(text: str, query: str | None, max_tokens: int = MAX_CONTEXT_TOKENS) -> str:
    """Like truncate_to_token_budget, but when `text` doesn't fit and a line
    containing `query` (case-insensitive substring) exists, centers the
    kept window on that line instead of always keeping the start of the
    file.

    Exists for read_file's targeted-section case (see agent_tools.py):
    always truncating from the top means a relevant section past the
    budget's cutoff -- e.g. a `[tool.pytest.ini_options]` block near the
    bottom of a long pyproject.toml -- is invisible no matter how tight or
    generous the budget is made, purely because of where it happens to sit
    in the file. Falls back to truncate_to_token_budget's from-the-top
    behavior when `query` is empty/None or matches no line -- a caller that
    doesn't know what it's looking for yet (or guessed wrong) is no worse
    off than before this function existed.
    """
    sanitized = sanitize_context(text)
    max_chars = max_tokens * _CHARS_PER_TOKEN
    if len(sanitized) <= max_chars:
        return sanitized
    if not query:
        return truncate_to_token_budget(text, max_tokens)

    lines = sanitized.splitlines()
    query_lower = query.lower()
    match_index = next((i for i, line in enumerate(lines) if query_lower in line.lower()), None)
    if match_index is None:
        return truncate_to_token_budget(text, max_tokens)

    # Expand outward from the matched line, one whole line at a time on
    # whichever side still has budget, until neither side can grow further
    # without exceeding max_chars -- keeps whole lines instead of an
    # arbitrary mid-line character cut.
    start = end = match_index
    kept_chars = len(lines[match_index])
    while True:
        grew = False
        if start > 0 and kept_chars + len(lines[start - 1]) + 1 <= max_chars:
            start -= 1
            kept_chars += len(lines[start]) + 1
            grew = True
        if end < len(lines) - 1 and kept_chars + len(lines[end + 1]) + 1 <= max_chars:
            end += 1
            kept_chars += len(lines[end]) + 1
            grew = True
        if not grew:
            break

    parts = []
    if start > 0:
        parts.append(f"... [{start} earlier lines omitted -- jumped to the section matching {query!r}]")
    parts.extend(lines[start : end + 1])
    if end < len(lines) - 1:
        parts.append(f"... [{len(lines) - end - 1} more lines omitted]")
    return "\n".join(parts)


# TOML/INI section headers (e.g. "[tool.pytest.ini_options]") -- the
# structural signal that actually matters for the motivating case (a
# config file's relevant section sitting past a from-the-top truncation's
# cutoff). Deliberately narrow rather than also matching generic top-level
# "key = value" lines: in TOML, ordinary key/value pairs are written at
# column 0 same as anywhere else (TOML uses [section] headers, not
# indentation, for scoping), so a "zero-indent key" pattern would match
# nearly every line in a typical TOML file and produce an "outline" that's
# really just most of the file -- no more useful than the plain truncation
# this exists to improve on.
_SECTION_HEADER_RE = re.compile(r"^\s*\[[^\]]+\]\s*$")
# Python top-level (and one-level-nested, e.g. inside a class) def/class --
# useful for source files, where TOML-style section headers don't apply.
_PY_DEF_RE = re.compile(r"^\s{0,4}(async def|def|class)\s+\w")


def extract_outline(text: str, max_tokens: int = MAX_CONTEXT_TOKENS) -> str | None:
    """Best-effort structural outline of `text` -- TOML/INI section headers
    and Python def/class lines, each with its real line number -- for
    read_file's no-query fallback (see agent_tools.py).

    Lets a caller that didn't guess a specific `query` still see a real map
    of the file's sections instead of only whatever fits within a from-the-
    top truncation, which for a long file can be nothing more informative
    than `[build-system]`/`[project]` boilerplate -- the outline alone is
    often enough to answer a "does this repo use X" question (seeing
    `[tool.pytest.ini_options]` in the list already confirms pytest is
    configured, with no need to see the section's actual contents), and
    even when it isn't, it tells the caller exactly what `query` to pass on
    a follow-up read_file to get that section in full.

    Returns None if nothing structural is found (caller falls back to
    plain from-the-top truncation in that case) -- this never produces a
    worse result than not trying.
    """
    sanitized = sanitize_context(text)
    lines = sanitized.splitlines()
    matches = [
        f"{i + 1:>5} | {line}"
        for i, line in enumerate(lines)
        if _SECTION_HEADER_RE.match(line) or _PY_DEF_RE.match(line)
    ]
    if not matches:
        return None

    max_chars = max_tokens * _CHARS_PER_TOKEN
    kept: list[str] = []
    used = 0
    omitted = 0
    for entry in matches:
        cost = len(entry) + 1
        if used + cost > max_chars:
            omitted += 1
            continue
        kept.append(entry)
        used += cost

    result = "\n".join(kept)
    if omitted:
        result += f"\n... [{omitted} more outline lines omitted]"
    return result
