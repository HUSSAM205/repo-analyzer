import json
import logging

from app.core.llm import LLMClient, Message

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Size guard
# ---------------------------------------------------------------------------
#
# Unlike domain_briefing (which only samples a file tree + a handful of
# symbols/README chars), this feature sends a *whole file*, line-numbered,
# to the LLM. A large file therefore costs much more prompt budget per
# character than domain_briefing's prompt does. We cap well below a typical
# 128k-token context window to leave headroom for: the system prompt, the
# per-line numbering overhead (adds several bytes per line on top of raw
# content), and a JSON response large enough to describe many blocks.
# 80,000 characters is roughly 20-25k tokens for source code -- generous for
# essentially any single source file a human would open in the code viewer,
# while keeping the request fast and inexpensive. Mirrors the reasoning
# behind the frontend's MAX_HIGHLIGHT_LENGTH (300KB) guard on Shiki
# highlighting, sized down for LLM-prompt economics rather than
# syntax-highlighter performance.
MAX_ANNOTATION_CONTENT_LENGTH = 80_000

_VALID_CATEGORIES = {"imports", "config_state", "business_logic", "handlers_endpoints"}

_SYSTEM_PROMPT = (
    "You are analyzing a single source code file to power an \"Annotated "
    "View\" code viewer feature. Segment the file into logical blocks and "
    "explain each one. Respond with strict JSON only -- no markdown code "
    "fences, no commentary, no text before or after the JSON. The response "
    "must be a JSON array of block objects. Each block object must have "
    "exactly these keys: \"category\" (one of exactly these four string "
    "values: \"imports\", \"config_state\", \"business_logic\", "
    "\"handlers_endpoints\" -- use no other values), \"start_line\" "
    "(1-indexed integer, inclusive), \"end_line\" (1-indexed integer, "
    "inclusive), \"logic_summary\" (1-2 plain-language sentences on what "
    "this block achieves), \"flow\" (1 sentence on key inputs and expected "
    "outputs), and \"tips\" (1-2 sentences on edge cases or optimization "
    "hints, or the literal string \"None apparent\" if there is genuinely "
    "nothing notable). Blocks should cover the file top-to-bottom with "
    "non-overlapping, contiguous-ish line ranges -- this is a best-effort "
    "semantic segmentation, not a precise parser, so exact line boundaries "
    "need not be perfect. Skip emitting a block for genuinely trivial or "
    "empty stretches (e.g. blank lines between blocks) rather than forcing "
    "every single line into some category."
)


class AnnotationUnavailableError(Exception):
    """Raised when AI code annotation could not be produced for a file.

    Covers LLM transport/provider errors as well as malformed/unparseable
    responses. There is no meaningful deterministic fallback for code
    segmentation + explanation (unlike domain_briefing's file-type
    distribution and manifest badges), so callers should surface a clean
    "annotation unavailable" response rather than fabricating block content.
    """


class FileTooLargeForAnnotationError(Exception):
    """Raised when a file exceeds MAX_ANNOTATION_CONTENT_LENGTH.

    Raised before any LLM call is attempted.
    """


def _numbered_lines(content: str) -> str:
    lines = content.splitlines()
    width = len(str(len(lines))) if lines else 1
    return "\n".join(f"{i:>{width}}: {line}" for i, line in enumerate(lines, start=1))


def _build_prompt(content: str, path: str) -> str:
    return (
        f"File path: {path}\n\n"
        "File contents, with each line prefixed by its 1-indexed line "
        "number (the \"N: \" prefix is not part of the source -- use it "
        "only to compute accurate start_line/end_line values):\n\n"
        f"{_numbered_lines(content)}"
    )


def _parse_llm_json(text: str) -> list[dict]:
    stripped = text.strip()
    if stripped.startswith("```"):
        # Models sometimes wrap "strict JSON only" output in a markdown
        # fence anyway. Strip the opening fence (with optional language
        # tag, e.g. "```json") and the closing fence.
        stripped = stripped[3:]
        if stripped[:4].lower() == "json":
            stripped = stripped[4:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()

    parsed = json.loads(stripped)
    if not isinstance(parsed, list):
        raise ValueError("LLM response was not a JSON array")

    blocks: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            raise ValueError("LLM response contained a non-object block")

        for key in ("category", "start_line", "end_line", "logic_summary", "flow", "tips"):
            if key not in item:
                raise ValueError(f"LLM response block missing required key: {key}")

        category = item["category"]
        if category not in _VALID_CATEGORIES:
            raise ValueError(f"LLM response block had invalid category: {category!r}")

        blocks.append(
            {
                "category": category,
                "start_line": int(item["start_line"]),
                "end_line": int(item["end_line"]),
                "logic_summary": str(item["logic_summary"]),
                "flow": str(item["flow"]),
                "tips": str(item["tips"]),
            }
        )

    return blocks


async def generate_code_annotations(content: str, path: str, llm_client: LLMClient) -> list[dict]:
    """Segment `content` into logical blocks with AI-generated explanations.

    Returns a list of block dicts shaped exactly like `CodeBlockAnnotation`
    in app.schemas.files. This is fundamentally an LLM task -- there is no
    meaningful deterministic fallback (unlike domain_briefing), so any
    failure raises rather than returning fabricated content:

    - FileTooLargeForAnnotationError if `content` exceeds
      MAX_ANNOTATION_CONTENT_LENGTH. Raised before any LLM call.
    - AnnotationUnavailableError on any LLM transport/provider error, or a
      malformed/unparseable response.
    """
    if len(content) > MAX_ANNOTATION_CONTENT_LENGTH:
        raise FileTooLargeForAnnotationError(
            f"File is {len(content)} characters, which exceeds the "
            f"{MAX_ANNOTATION_CONTENT_LENGTH}-character limit for AI annotation."
        )

    try:
        prompt = _build_prompt(content, path)
        messages = [Message(role="user", content=prompt)]

        accumulated = ""
        llm_error: str | None = None
        async for event in llm_client.stream_chat(messages, tools=[], system_prompt=_SYSTEM_PROMPT):
            if event.type == "token":
                accumulated += event.token or ""
            elif event.type == "error":
                llm_error = event.error

        if llm_error is not None:
            raise RuntimeError(f"LLM provider returned an error: {llm_error}")

        return _parse_llm_json(accumulated)
    except FileTooLargeForAnnotationError:
        raise
    except Exception as exc:
        logger.warning("Code annotation LLM call failed for path=%s", path, exc_info=True)
        raise AnnotationUnavailableError(f"AI annotation is currently unavailable for {path}") from exc
