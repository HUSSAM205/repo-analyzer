import json
import logging

from tree_sitter import Node
from tree_sitter_languages import get_parser

from app.core.ast_parser import language_for_path
from app.core.llm import LLMClient, Message
from app.core.token_budget import MAX_CONTEXT_CHARS, sanitize_context

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Size guard
# ---------------------------------------------------------------------------
#
# This feature sends a whole file's worth of content to the LLM (split across
# per-block snippets in one batched prompt, see _build_summary_prompt). A
# large file therefore costs much more prompt budget per character than
# domain_briefing's prompt does. 80,000 characters is roughly 20-25k tokens
# for source code -- generous for essentially any single source file a human
# would open in the code viewer, while keeping the request fast and
# inexpensive. Mirrors the reasoning behind the frontend's
# MAX_HIGHLIGHT_LENGTH (300KB) guard on Shiki highlighting, sized down for
# LLM-prompt economics rather than syntax-highlighter performance.
MAX_ANNOTATION_CONTENT_LENGTH = 80_000

_VALID_CATEGORIES = {"imports", "config_state", "business_logic", "handlers_endpoints"}

_IMPORT_NODE_TYPES: dict[str, set[str]] = {
    "python": {"import_statement", "import_from_statement"},
    "javascript": {"import_statement"},
    "typescript": {"import_statement"},
    "tsx": {"import_statement"},
    "go": {"import_declaration"},
    "java": {"import_declaration"},
}

_DEFINITION_NODE_TYPES: dict[str, set[str]] = {
    "python": {"function_definition", "class_definition", "decorated_definition"},
    "javascript": {"function_declaration", "class_declaration", "method_definition"},
    "typescript": {"function_declaration", "class_declaration", "method_definition"},
    "tsx": {"function_declaration", "class_declaration", "method_definition"},
    "go": {"function_declaration", "method_declaration", "type_declaration"},
    "java": {"class_declaration", "method_declaration", "interface_declaration"},
}

# Method names that, when called as `something.<method>(...)` at the top
# level of a file, almost always mean "this is registering an event
# listener or route handler" (socket.io's `.on`, Express-style
# `.get`/`.post`/etc, DOM's `.addEventListener`, pub/sub's `.subscribe`) --
# exactly the "Socket.io event listener" style block a human would call out
# when reading the file, even though it's neither an import nor a named
# function/class definition.
_HANDLER_METHOD_NAMES = {
    "on", "once", "addEventListener", "get", "post", "put", "delete", "patch",
    "use", "listen", "subscribe", "route", "handle",
}

_HANDLER_NAME_HINTS = ("handle", "route", "endpoint", "controller", "listener", "on_")


class FileTooLargeForAnnotationError(Exception):
    """Raised when a file exceeds MAX_ANNOTATION_CONTENT_LENGTH.

    Raised before any LLM call is attempted.
    """


def _definition_target(node: Node) -> Node:
    # Python wraps a decorated function/class in a `decorated_definition`
    # node whose actual function_definition/class_definition is a child --
    # unwrap it so name/kind extraction looks at the real definition, not
    # the decorator wrapper.
    if node.type == "decorated_definition":
        for child in node.children:
            if child.type in ("function_definition", "class_definition"):
                return child
    return node


def _node_name(node: Node, source_bytes: bytes) -> str | None:
    target = _definition_target(node)
    name_node = target.child_by_field_name("name")
    if name_node is not None:
        return source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
    return None


def _category_for_definition(node: Node, source_bytes: bytes) -> str:
    target = _definition_target(node)
    is_class = "class" in target.type or "interface" in target.type
    if is_class:
        return "business_logic"

    text = source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
    header = text.split("\n", 1)[0].lower()
    if any(hint in header for hint in _HANDLER_NAME_HINTS):
        return "handlers_endpoints"
    if "@app." in text[:200] or "@router." in text[:200]:
        return "handlers_endpoints"
    return "business_logic"


def _is_class_node(node: Node) -> bool:
    target = _definition_target(node)
    return "class" in target.type or "interface" in target.type


def _find_call_expression(node: Node) -> Node | None:
    if node.type == "call_expression":
        return node
    for child in node.children:
        found = _find_call_expression(child)
        if found is not None:
            return found
    return None


def _handler_call_label(node: Node, source_bytes: bytes) -> str | None:
    call = _find_call_expression(node)
    if call is None:
        return None
    callee = call.child_by_field_name("function")
    if callee is None:
        return None
    callee_text = source_bytes[callee.start_byte:callee.end_byte].decode("utf-8", errors="replace")
    method = callee_text.rsplit(".", 1)[-1]
    if method not in _HANDLER_METHOD_NAMES:
        return None

    args = call.child_by_field_name("arguments")
    first_literal: str | None = None
    if args is not None:
        for child in args.children:
            if child.type in ("string", "string_literal", "template_string"):
                raw = source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
                first_literal = raw.strip("'\"`")
                break

    return f"{method}('{first_literal}')" if first_literal else f"{callee_text}(...)"


def _unwrap_export(node: Node) -> Node:
    # `export function foo() {}` / `export default class {}` / `export const
    # x = ...` wrap the real statement in an export_statement -- classify the
    # thing actually being exported, not the wrapper, while still spanning
    # the whole export statement's line range in the caller.
    if node.type != "export_statement":
        return node
    for child in node.children:
        if child.type not in ("export", "default"):
            return child
    return node


def _whole_file_block(total_lines: int) -> dict:
    return {
        "category": "business_logic",
        "node_type": "text",
        "symbol_name": None,
        "start_line": 1,
        "end_line": max(total_lines, 1),
    }


def _local_blocks(content: str, path: str) -> list[dict]:
    """Split `content` into logical blocks using local (non-LLM) AST parsing.

    Walks the file's top-level statements, categorizing each as an import
    block, a function/class definition, an event-listener/route-handler call
    (e.g. `socket.on('connect', ...)`), or a generic top-level statement.
    Always returns at least one block covering the whole file, even for an
    unsupported language or a file tree-sitter can't usefully parse.
    """
    lines = content.splitlines()
    if not lines:
        return []

    language = language_for_path(path)
    if language is None:
        return [_whole_file_block(len(lines))]

    try:
        parser = get_parser(language)
        source_bytes = content.encode("utf-8")
        tree = parser.parse(source_bytes)
    except Exception:
        logger.warning("Local AST segmentation failed for path=%s", path, exc_info=True)
        return [_whole_file_block(len(lines))]

    top_level = list(tree.root_node.children)
    if not top_level:
        return [_whole_file_block(len(lines))]

    import_types = _IMPORT_NODE_TYPES.get(language, set())
    definition_types = _DEFINITION_NODE_TYPES.get(language, set())

    raw_blocks: list[dict] = []
    for outer_node in top_level:
        start_line = outer_node.start_point[0] + 1
        end_line = outer_node.end_point[0] + 1
        if end_line < start_line:
            continue

        node = _unwrap_export(outer_node)

        if node.type in import_types:
            raw_blocks.append({
                "category": "imports", "node_type": "import", "symbol_name": None,
                "start_line": start_line, "end_line": end_line,
            })
        elif node.type in definition_types:
            raw_blocks.append({
                "category": _category_for_definition(node, source_bytes),
                "node_type": "class" if _is_class_node(node) else "function",
                "symbol_name": _node_name(node, source_bytes),
                "start_line": start_line, "end_line": end_line,
            })
        else:
            handler_label = _handler_call_label(node, source_bytes)
            if handler_label:
                raw_blocks.append({
                    "category": "handlers_endpoints", "node_type": "handler_call",
                    "symbol_name": handler_label, "start_line": start_line, "end_line": end_line,
                })
            else:
                raw_blocks.append({
                    "category": "config_state", "node_type": "statement", "symbol_name": None,
                    "start_line": start_line, "end_line": end_line,
                })

    return _merge_adjacent_same_kind(raw_blocks) or [_whole_file_block(len(lines))]


def _merge_adjacent_same_kind(raw_blocks: list[dict]) -> list[dict]:
    # Collapse runs of consecutive imports (or consecutive stray statements)
    # into one block -- a file with 10 import lines shouldn't produce 10
    # near-identical "Import statements" blocks. Function/class/handler-call
    # blocks are each kept distinct even when adjacent, since each is a
    # meaningfully separate unit worth its own explanation.
    merged: list[dict] = []
    for block in raw_blocks:
        mergeable = block["node_type"] in ("import", "statement")
        if (
            mergeable
            and merged
            and merged[-1]["category"] == block["category"]
            and merged[-1]["node_type"] == block["node_type"]
        ):
            merged[-1]["end_line"] = block["end_line"]
        else:
            merged.append(dict(block))
    return merged


def _heuristic_block(block: dict) -> dict:
    node_type = block["node_type"]
    symbol_name = block.get("symbol_name")
    category = block["category"]

    if node_type == "class":
        summary = f"Class: {symbol_name}" if symbol_name else "Class definition"
    elif node_type == "function":
        summary = f"Function: {symbol_name}" if symbol_name else "Function definition"
    elif node_type == "handler_call":
        summary = f"Event/route handler: {symbol_name}" if symbol_name else "Event/route handler"
    elif node_type == "import":
        summary = "Import statements"
    elif category == "config_state":
        summary = "Setup / top-level configuration"
    else:
        summary = "Code block"

    return {
        "category": category,
        "start_line": block["start_line"],
        "end_line": block["end_line"],
        "logic_summary": f"{summary}. AI explanation is temporarily unavailable -- showing detected code structure only.",
        "flow": "AI explanation is temporarily unavailable.",
        "tips": "AI explanation is temporarily unavailable -- try again in a moment.",
        "source": "heuristic",
    }


# ELI5 ("Explain Like I'm 5") framing throughout: this is the primary way a
# total beginner is meant to learn from a real, unfamiliar codebase, so every
# field is written for someone who may not know what a "handler" or a
# "decorator" is yet -- plain words, no unexplained jargon, a friendly tone.
# The three fields map directly to the frontend's three labeled cards (see
# code-viewer.tsx's AnnotationField usages): logic_summary is "What this
# does", flow is "Why it exists / where it connects", tips is "Practical
# tips for beginners". The JSON keys themselves are unchanged from before
# this rewrite -- only what's asked for in each one changed -- so no schema
# migration or frontend contract change was needed for this feature.
_SUMMARY_SYSTEM_PROMPT = (
    "You are writing beginner-friendly, \"Explain Like I'm 5\" annotations for "
    "a source code file that has already been split into numbered blocks for "
    "an \"Annotated View\" code viewer feature. Your reader is a total "
    "beginner who may be looking at real production code for the first time "
    "-- avoid jargon, or briefly define any technical term you must use (e.g. "
    "\"a decorator (a Python feature that wraps a function to add behavior "
    "to it)\"). Prefer everyday analogies over technical descriptions. "
    "Respond with strict JSON only -- no markdown code fences, no commentary, "
    "no text before or after the JSON. The response must be a JSON array. "
    "Each element must have exactly these keys: \"index\" (the integer block "
    "index as given), \"logic_summary\" (1-2 short sentences, in dead-simple "
    "non-technical language, on WHAT this piece of code does -- imagine "
    "explaining it to a curious 10-year-old), \"flow\" (1-2 sentences on WHY "
    "this code exists and HOW it connects to the rest of the project -- what "
    "calls it, what it depends on, or what would break without it), and "
    "\"tips\" (1-2 practical, encouraging sentences aimed at a beginner: how "
    "they could learn from this pattern, safely experiment with or modify it, "
    "or reuse a similar approach in their own projects -- or the literal "
    "string \"Nothing extra to add here.\" if the block is too trivial for a "
    "tip). Include every block index exactly once."
)


def _build_summary_prompt(blocks: list[dict], content_lines: list[str], path: str) -> str:
    parts = [f"File path: {path}\n"]
    # Keeps the batched prompt within the shared repo-context token budget
    # (see token_budget.py) regardless of how many blocks a file has --
    # confirmed live, a single unbounded annotation prompt for a ~1400-line
    # file hit Groq's "tokens per minute" 413 limit. Blocks left out here
    # simply have no entry in the LLM's response, and
    # generate_code_annotations already falls back to a heuristic label for
    # any block index missing from that response, so no extra bookkeeping
    # is needed for the blocks this loop drops.
    budget_remaining = MAX_CONTEXT_CHARS
    for i, block in enumerate(blocks):
        snippet = sanitize_context("\n".join(content_lines[block["start_line"] - 1:block["end_line"]]))
        block_text = (
            f"--- Block {i} (category={block['category']}, lines "
            f"{block['start_line']}-{block['end_line']}) ---\n{snippet}\n"
        )
        if len(block_text) > budget_remaining:
            break
        parts.append(block_text)
        budget_remaining -= len(block_text)
    return "\n".join(parts)


def _parse_summary_json(text: str) -> dict[int, dict]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped[3:]
        if stripped[:4].lower() == "json":
            stripped = stripped[4:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()

    parsed = json.loads(stripped)
    if not isinstance(parsed, list):
        raise ValueError("LLM response was not a JSON array")

    # Lenient per-item parsing: a malformed or missing individual entry just
    # means that one block falls back to a heuristic label (see
    # generate_code_annotations) -- it must not take down every other block
    # in the file that the model summarized correctly.
    summaries: dict[int, dict] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item["index"])
            summaries[index] = {
                "logic_summary": str(item["logic_summary"]),
                "flow": str(item["flow"]),
                "tips": str(item["tips"]),
            }
        except (KeyError, TypeError, ValueError):
            continue
    return summaries


async def generate_code_annotations(content: str, path: str, llm_client: LLMClient) -> tuple[list[dict], bool]:
    """Segment `content` into logical blocks and explain each one.

    Segmentation always happens locally first (tree-sitter, see
    _local_blocks) -- imports, function/class definitions, and
    event-listener/route-handler calls are detected deterministically before
    any LLM is involved. The LLM is then asked only to summarize the
    already-segmented blocks (a smaller, more constrained task than the
    original single-shot "segment AND explain" prompt).

    This function never raises for an LLM failure -- a Groq timeout, rate
    limit, transport error, or malformed/partial JSON response all degrade to
    locally-generated heuristic labels (e.g. "Function: sendMessage",
    "Event/route handler: on('connect')") so the caller always has something
    to show. FileTooLargeForAnnotationError is the only case that still
    raises, since it's a distinct, informative state (not a failure) and is
    checked before any LLM call.

    Returns (blocks, used_fallback). `used_fallback` is True only when the
    LLM contributed nothing at all (so the caller knows not to cache a
    heuristic-only result -- a later request should retry the LLM).
    """
    if len(content) > MAX_ANNOTATION_CONTENT_LENGTH:
        raise FileTooLargeForAnnotationError(
            f"File is {len(content)} characters, which exceeds the "
            f"{MAX_ANNOTATION_CONTENT_LENGTH}-character limit for AI annotation."
        )

    local_blocks = _local_blocks(content, path)
    heuristic_blocks = [_heuristic_block(b) for b in local_blocks]
    if not local_blocks:
        return heuristic_blocks, True

    try:
        content_lines = content.splitlines()
        prompt = _build_summary_prompt(local_blocks, content_lines, path)
        messages = [Message(role="user", content=prompt)]

        accumulated = ""
        llm_error: str | None = None
        async for event in llm_client.stream_chat(messages, tools=[], system_prompt=_SUMMARY_SYSTEM_PROMPT):
            if event.type == "token":
                accumulated += event.token or ""
            elif event.type == "error":
                llm_error = event.error

        if llm_error is not None:
            raise RuntimeError(f"LLM provider returned an error: {llm_error}")

        summaries = _parse_summary_json(accumulated)
    except Exception:
        logger.warning(
            "Code annotation LLM summarization failed for path=%s -- using local heuristic fallback",
            path, exc_info=True,
        )
        return heuristic_blocks, True

    result: list[dict] = []
    for i, block in enumerate(local_blocks):
        summary = summaries.get(i)
        if summary is None:
            result.append(heuristic_blocks[i])
        else:
            result.append({
                "category": block["category"],
                "start_line": block["start_line"],
                "end_line": block["end_line"],
                "logic_summary": summary["logic_summary"],
                "flow": summary["flow"],
                "tips": summary["tips"],
                "source": "ai",
            })
    return result, False
