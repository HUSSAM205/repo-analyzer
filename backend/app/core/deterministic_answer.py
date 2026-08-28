"""Tier 3 of chat's fallback chain (see chat.py's _graceful_degraded_reply):
a best-effort, no-LLM answer built by keyword-matching the user's question
against this repo's already-indexed files and pulling real code snippets
from the strongest match -- not just a list of file names -- so the reply
is genuinely code-grounded even with zero AI calls. Used only once both
the primary and fallback model (GroqClient's own Tier 1/Tier 2 -- see
llm_providers.py) are exhausted.
"""

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import File

_WORD_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]{2,}")
# Common question/filler words -- excluded so "Where is the entry point?"
# extracts to {"entry", "point"}, not {"where", "the", "entry", "point"}.
_STOPWORDS = frozenset({
    "the", "is", "are", "was", "were", "what", "where", "when", "why", "how",
    "does", "do", "did", "this", "that", "these", "those", "and", "for",
    "with", "from", "into", "about", "explain", "tell", "show", "find",
    "can", "you", "your", "please", "repo", "repository", "code", "file",
    "files", "function", "class", "work", "works", "there", "here", "who",
    "which", "add", "new", "use", "used", "using", "flow", "data",
})
_MAX_MATCHED_FILES = 5
_MAX_KEYWORDS_SHOWN = 5
_MAX_SNIPPET_FILES = 2
_SNIPPET_CONTEXT_LINES = 4
_SNIPPET_MAX_LINE_LENGTH = 200
# Bounds the content-scan fallback's cost -- File.content has no full-text
# index (CodeChunk.content_tsv does, but that table is empty whenever
# Settings.enable_embedding is off, which is this deployment's actual
# production config -- see render.yaml), so this scan is plain Python
# substring matching over a capped number of rows, not a DB-side LIKE
# across the whole repo.
_CONTENT_SCAN_SAMPLE_SIZE = 200


def _extract_keywords(question: str) -> list[str]:
    words = {w.lower() for w in _WORD_RE.findall(question)}
    return sorted(w for w in words if w not in _STOPWORDS)


def _keyword_score(text_lower: str, keywords: list[str]) -> int:
    return sum(1 for kw in keywords if kw in text_lower)


def _extract_snippet(content: str, keywords: list[str]) -> str | None:
    """Returns a small, line-numbered window of `content` centered on the
    first line that actually mentions one of `keywords` -- a real excerpt,
    not the whole file. None if no line matches (can happen when a file
    was matched by path alone, with no keyword actually appearing in its
    body).
    """
    lines = content.splitlines()
    match_line = next(
        (i for i, line in enumerate(lines) if _keyword_score(line.lower(), keywords) > 0), None
    )
    if match_line is None:
        return None

    start = max(0, match_line - _SNIPPET_CONTEXT_LINES)
    end = min(len(lines), match_line + _SNIPPET_CONTEXT_LINES + 1)
    numbered = []
    for i in range(start, end):
        text = lines[i][:_SNIPPET_MAX_LINE_LENGTH]
        numbered.append(f"{i + 1:>4} | {text}")
    return "\n".join(numbered)


async def build_deterministic_answer(db: AsyncSession, repo_id: UUID, question: str) -> str | None:
    """Returns a keyword-grounded reply (file matches plus a real code
    snippet from the strongest one), or None if no keyword could be
    extracted or nothing in the repo matches -- the caller (chat.py) falls
    back further (a generic, domain_briefing-based reply) in that case.
    Never raises: a DB error here should fall back the same way a "no
    match" result does, not break the whole degraded-reply path.
    """
    keywords = _extract_keywords(question)
    if not keywords:
        return None

    try:
        result = await db.execute(select(File.path).where(File.repo_id == repo_id))
        all_paths = result.scalars().all()
        if not all_paths:
            return None

        path_matches = sorted(
            (p for p in all_paths if _keyword_score(p.lower(), keywords) > 0),
            key=lambda p: _keyword_score(p.lower(), keywords),
            reverse=True,
        )[:_MAX_MATCHED_FILES]

        content_by_path: dict[str, str] = {}
        if not path_matches:
            # No filename/path match -- fall back to scanning a bounded
            # sample of file content instead of giving up immediately.
            sample_result = await db.execute(
                select(File.path, File.content).where(File.repo_id == repo_id).limit(_CONTENT_SCAN_SAMPLE_SIZE)
            )
            rows = sample_result.all()
            content_by_path = {path: content for path, content in rows}
            scored = [(path, _keyword_score(content.lower(), keywords)) for path, content in rows]
            path_matches = [p for p, score in sorted(scored, key=lambda x: x[1], reverse=True) if score > 0][
                :_MAX_MATCHED_FILES
            ]

        if not path_matches:
            return None

        # Fetch content for the top matches that weren't already loaded by
        # the content-scan branch above, so a snippet can be pulled from a
        # path-matched file too (e.g. the question named a file by name).
        missing = [p for p in path_matches[:_MAX_SNIPPET_FILES] if p not in content_by_path]
        if missing:
            content_result = await db.execute(
                select(File.path, File.content).where(File.repo_id == repo_id, File.path.in_(missing))
            )
            content_by_path.update(dict(content_result.all()))
    except Exception:
        return None

    file_list = "\n".join(f"- `{p}`" for p in path_matches)
    shown_keywords = ", ".join(keywords[:_MAX_KEYWORDS_SHOWN])

    snippet_blocks: list[str] = []
    for path in path_matches[:_MAX_SNIPPET_FILES]:
        content = content_by_path.get(path)
        if not content:
            continue
        snippet = _extract_snippet(content, keywords)
        if snippet:
            snippet_blocks.append(f"`{path}`:\n```\n{snippet}\n```")

    parts = [
        "I'm temporarily unable to reach the AI provider, so here's a keyword match against this "
        f'repo\'s indexed files instead of a full answer: based on "{shown_keywords}", these look '
        f"most relevant:\n\n{file_list}",
    ]
    if snippet_blocks:
        parts.append("\n\nRelevant excerpt" + ("s" if len(snippet_blocks) > 1 else "") + ":\n\n" + "\n\n".join(snippet_blocks))
    parts.append(
        "\n\nOpen one of these in the Code tab to look directly, or resend your question in a moment "
        "once the AI is back for a real, code-grounded explanation."
    )
    return "".join(parts)
