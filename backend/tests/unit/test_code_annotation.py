import json

import pytest

from app.core.code_annotation import (
    MAX_ANNOTATION_CONTENT_LENGTH,
    FileTooLargeForAnnotationError,
    _build_summary_prompt,
    _local_blocks,
    generate_code_annotations,
)
from app.core.llm import FakeLLMClient, LLMEvent, ScriptedTurn
from app.core.token_budget import MAX_CONTEXT_CHARS

PY_SAMPLE = (
    "import os\n"
    "import sys\n"
    "\n"
    "\n"
    "def handler():\n"
    "    return os.getcwd()\n"
)


def _summary_json(indices: list[int]) -> str:
    return json.dumps(
        [
            {
                "index": i,
                "logic_summary": f"Summary for block {i}.",
                "flow": f"Flow for block {i}.",
                "tips": "None apparent",
            }
            for i in indices
        ]
    )


# ---------------------------------------------------------------------------
# Local segmentation (no LLM involved)
# ---------------------------------------------------------------------------


def test_local_blocks_detects_imports_and_function():
    blocks = _local_blocks(PY_SAMPLE, "app/main.py")

    assert blocks[0]["category"] == "imports"
    assert blocks[0]["node_type"] == "import"
    assert blocks[0]["start_line"] == 1
    assert blocks[0]["end_line"] == 2

    function_blocks = [b for b in blocks if b["node_type"] == "function"]
    assert len(function_blocks) == 1
    assert function_blocks[0]["symbol_name"] == "handler"


def test_local_blocks_detects_class():
    content = "class Greeter:\n    def greet(self):\n        return 'hi'\n"
    blocks = _local_blocks(content, "app/greeter.py")

    class_blocks = [b for b in blocks if b["node_type"] == "class"]
    assert len(class_blocks) == 1
    assert class_blocks[0]["symbol_name"] == "Greeter"
    assert class_blocks[0]["category"] == "business_logic"


def test_local_blocks_detects_socket_io_style_event_listener():
    content = (
        "const socket = io('http://localhost:3000');\n"
        "\n"
        "socket.on('connect', () => {\n"
        "  console.log('connected');\n"
        "});\n"
    )
    blocks = _local_blocks(content, "public/client.js")

    handler_blocks = [b for b in blocks if b["node_type"] == "handler_call"]
    assert len(handler_blocks) == 1
    assert "connect" in handler_blocks[0]["symbol_name"]
    assert handler_blocks[0]["category"] == "handlers_endpoints"


def test_local_blocks_falls_back_to_whole_file_for_unsupported_language():
    blocks = _local_blocks("some content\nwith no known extension\n", "notes.txt")

    assert len(blocks) == 1
    assert blocks[0]["node_type"] == "text"
    assert blocks[0]["start_line"] == 1


def test_local_blocks_handles_empty_content():
    assert _local_blocks("", "app/empty.py") == []


# ---------------------------------------------------------------------------
# generate_code_annotations: success and fallback paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_well_formed_response_uses_ai_summaries_and_is_not_a_fallback():
    blocks_preview = _local_blocks(PY_SAMPLE, "app/main.py")
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text=_summary_json(list(range(len(blocks_preview)))))])

    blocks, used_fallback = await generate_code_annotations(PY_SAMPLE, "app/main.py", llm_client)

    assert used_fallback is False
    assert all(b["source"] == "ai" for b in blocks)
    assert blocks[0]["logic_summary"] == "Summary for block 0."


@pytest.mark.asyncio
async def test_strips_markdown_fences_from_llm_response():
    blocks_preview = _local_blocks(PY_SAMPLE, "app/main.py")
    fenced_text = "```json\n" + _summary_json(list(range(len(blocks_preview)))) + "\n```"
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text=fenced_text)])

    blocks, used_fallback = await generate_code_annotations(PY_SAMPLE, "app/main.py", llm_client)

    assert used_fallback is False
    assert all(b["source"] == "ai" for b in blocks)


@pytest.mark.asyncio
async def test_malformed_json_falls_back_to_heuristic_blocks_never_raises():
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text="this is not valid JSON at all")])

    blocks, used_fallback = await generate_code_annotations(PY_SAMPLE, "app/main.py", llm_client)

    assert used_fallback is True
    assert len(blocks) > 0
    assert all(b["source"] == "heuristic" for b in blocks)
    # The user must always see *some* structure, even with AI unavailable.
    assert any("Function" in b["logic_summary"] for b in blocks)


@pytest.mark.asyncio
async def test_non_array_json_falls_back_to_heuristic_blocks():
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text=json.dumps({"not": "an array"}))])

    blocks, used_fallback = await generate_code_annotations(PY_SAMPLE, "app/main.py", llm_client)

    assert used_fallback is True
    assert all(b["source"] == "heuristic" for b in blocks)


@pytest.mark.asyncio
async def test_partial_response_only_falls_back_the_missing_blocks():
    blocks_preview = _local_blocks(PY_SAMPLE, "app/main.py")
    assert len(blocks_preview) >= 2
    # Only summarize the first block -- the rest are missing from the
    # response, simulating a truncated/partial LLM output.
    partial_text = _summary_json([0])
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text=partial_text)])

    blocks, used_fallback = await generate_code_annotations(PY_SAMPLE, "app/main.py", llm_client)

    # The call succeeded overall (used_fallback reflects total failure only).
    assert used_fallback is False
    assert blocks[0]["source"] == "ai"
    assert any(b["source"] == "heuristic" for b in blocks[1:])


@pytest.mark.asyncio
async def test_llm_error_event_falls_back_to_heuristic_blocks():
    class ErroringLLMClient:
        async def stream_chat(self, messages, tools, system_prompt):
            yield LLMEvent(type="error", error="upstream unavailable")

    blocks, used_fallback = await generate_code_annotations(PY_SAMPLE, "app/main.py", ErroringLLMClient())

    assert used_fallback is True
    assert all(b["source"] == "heuristic" for b in blocks)


@pytest.mark.asyncio
async def test_llm_raising_exception_falls_back_to_heuristic_blocks():
    class RaisingLLMClient:
        async def stream_chat(self, messages, tools, system_prompt):
            raise ConnectionError("network is down")
            yield  # pragma: no cover - makes this an async generator

    blocks, used_fallback = await generate_code_annotations(PY_SAMPLE, "app/main.py", RaisingLLMClient())

    assert used_fallback is True
    assert all(b["source"] == "heuristic" for b in blocks)


@pytest.mark.asyncio
async def test_oversized_file_raises_without_consuming_llm_turns():
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text=_summary_json([0]))])
    oversized_content = "x" * (MAX_ANNOTATION_CONTENT_LENGTH + 1)

    with pytest.raises(FileTooLargeForAnnotationError):
        await generate_code_annotations(oversized_content, "app/huge.py", llm_client)

    # The size guard must short-circuit before any LLM call -- the scripted
    # turn should still be sitting unconsumed.
    assert len(llm_client._turns) == 1


@pytest.mark.asyncio
async def test_prompt_includes_line_numbers_and_path():
    captured_messages = []

    class CapturingLLMClient:
        async def stream_chat(self, messages, tools, system_prompt):
            captured_messages.append(messages)
            assert tools == []
            blocks_preview = _local_blocks(PY_SAMPLE, "app/main.py")
            for word in _summary_json(list(range(len(blocks_preview)))).split(" "):
                yield LLMEvent(type="token", token=word + " ")

    await generate_code_annotations(PY_SAMPLE, "app/main.py", CapturingLLMClient())

    assert len(captured_messages) == 1
    prompt = captured_messages[0][0].content
    assert "app/main.py" in prompt
    assert "Block 0" in prompt


# ---------------------------------------------------------------------------
# Prompt token budget
# ---------------------------------------------------------------------------


def _three_blocks_where_the_last_exceeds_budget():
    # Each block's snippet is ~100 lines * 60 chars =~ 6,100 chars: the
    # first two fit within MAX_CONTEXT_CHARS (16,000) cumulatively, but the
    # third would push the running total past it. Total content (~18KB)
    # stays comfortably under MAX_ANNOTATION_CONTENT_LENGTH (80,000).
    blocks = [
        {"category": "business_logic", "start_line": 1, "end_line": 100},
        {"category": "business_logic", "start_line": 101, "end_line": 200},
        {"category": "business_logic", "start_line": 201, "end_line": 300},
    ]
    content_lines = ["x" * 60 for _ in range(300)]
    return blocks, content_lines


def test_build_summary_prompt_drops_blocks_once_the_token_budget_is_exceeded():
    # Confirmed live: an unbounded annotation prompt for a real ~1400-line
    # file hit Groq's "tokens per minute" 413 limit. Later blocks must be
    # left out of the prompt entirely once the budget is exceeded (they
    # still get a heuristic label from generate_code_annotations, just not
    # an AI-written one).
    blocks, content_lines = _three_blocks_where_the_last_exceeds_budget()

    prompt = _build_summary_prompt(blocks, content_lines, "big/file.py")

    assert len(prompt) <= MAX_CONTEXT_CHARS + 1000  # +headroom for the small fixed preamble/header text
    assert "Block 0" in prompt
    assert "Block 2" not in prompt


def _padded_function(name: str, n_lines: int = 110) -> str:
    # Realistic, parseable Python -- generate_code_annotations runs its own
    # real tree-sitter segmentation internally (unlike the direct
    # _build_summary_prompt test above), so the fixture needs actual valid
    # source, not arbitrary filler text, for _local_blocks to detect three
    # separate function blocks with predictable sizes.
    body = "\n".join(f"    line_{i} = 'x' * 50  # padding to control block size" for i in range(n_lines))
    return f"def {name}():\n{body}\n    return None\n"


@pytest.mark.asyncio
async def test_blocks_dropped_from_the_prompt_still_get_a_heuristic_label():
    content = _padded_function("func_a") + "\n" + _padded_function("func_b") + "\n" + _padded_function("func_c")
    local_blocks_preview = _local_blocks(content, "big/file.py")
    assert len(local_blocks_preview) == 3  # sanity check the fixture parses as expected

    prompt = _build_summary_prompt(local_blocks_preview, content.splitlines(), "big/file.py")
    assert "Block 2" not in prompt  # sanity check this fixture actually exceeds the budget

    class CapturingLLMClient:
        async def stream_chat(self, messages, tools, system_prompt):
            # Only summarize whatever indices actually made it into the
            # prompt -- mirrors what a real model would do (it can't
            # summarize a block it never saw).
            summarized_indices = [0, 1] if "Block 1" in prompt else [0]
            text = json.dumps(
                [
                    {"index": i, "logic_summary": f"s{i}", "flow": f"f{i}", "tips": "None apparent"}
                    for i in summarized_indices
                ]
            )
            for word in text.split(" "):
                yield LLMEvent(type="token", token=word + " ")

    result_blocks, used_fallback = await generate_code_annotations(
        content, "big/file.py", CapturingLLMClient()
    )

    assert used_fallback is False
    assert result_blocks[0]["source"] == "ai"
    assert result_blocks[-1]["source"] == "heuristic"
