import json

import pytest

from app.core.code_annotation import (
    MAX_ANNOTATION_CONTENT_LENGTH,
    AnnotationUnavailableError,
    FileTooLargeForAnnotationError,
    generate_code_annotations,
)
from app.core.llm import FakeLLMClient, LLMEvent, ScriptedTurn

VALID_JSON_TEXT = json.dumps(
    [
        {
            "category": "imports",
            "start_line": 1,
            "end_line": 3,
            "logic_summary": "Imports the standard library modules used below.",
            "flow": "No inputs; makes downstream symbols available.",
            "tips": "None apparent",
        },
        {
            "category": "handlers_endpoints",
            "start_line": 5,
            "end_line": 10,
            "logic_summary": "Defines the FastAPI route handler for creating a widget.",
            "flow": "Takes a validated request body, returns the created widget as JSON.",
            "tips": "Consider rate limiting this endpoint.",
        },
    ]
)


@pytest.mark.asyncio
async def test_well_formed_response_parses_correctly():
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text=VALID_JSON_TEXT)])

    blocks = await generate_code_annotations("import os\nimport sys\n", "app/main.py", llm_client)

    assert len(blocks) == 2
    assert blocks[0]["category"] == "imports"
    assert blocks[0]["start_line"] == 1
    assert blocks[0]["end_line"] == 3
    assert blocks[1]["category"] == "handlers_endpoints"
    assert blocks[1]["logic_summary"] == "Defines the FastAPI route handler for creating a widget."


@pytest.mark.asyncio
async def test_strips_markdown_fences_from_llm_response():
    fenced_text = "```json\n" + VALID_JSON_TEXT + "\n```"
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text=fenced_text)])

    blocks = await generate_code_annotations("import os\n", "app/main.py", llm_client)

    assert len(blocks) == 2
    assert blocks[0]["category"] == "imports"


@pytest.mark.asyncio
async def test_malformed_json_raises_annotation_unavailable():
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text="this is not valid JSON at all")])

    with pytest.raises(AnnotationUnavailableError):
        await generate_code_annotations("import os\n", "app/main.py", llm_client)


@pytest.mark.asyncio
async def test_non_array_json_raises_annotation_unavailable():
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text=json.dumps({"not": "an array"}))])

    with pytest.raises(AnnotationUnavailableError):
        await generate_code_annotations("import os\n", "app/main.py", llm_client)


@pytest.mark.asyncio
async def test_invalid_category_raises_annotation_unavailable():
    bad_text = json.dumps(
        [
            {
                "category": "not_a_real_category",
                "start_line": 1,
                "end_line": 2,
                "logic_summary": "x",
                "flow": "x",
                "tips": "x",
            }
        ]
    )
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text=bad_text)])

    with pytest.raises(AnnotationUnavailableError):
        await generate_code_annotations("import os\n", "app/main.py", llm_client)


@pytest.mark.asyncio
async def test_missing_key_raises_annotation_unavailable():
    bad_text = json.dumps(
        [
            {
                "category": "imports",
                "start_line": 1,
                "end_line": 2,
                "logic_summary": "x",
                # "flow" missing
                "tips": "x",
            }
        ]
    )
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text=bad_text)])

    with pytest.raises(AnnotationUnavailableError):
        await generate_code_annotations("import os\n", "app/main.py", llm_client)


@pytest.mark.asyncio
async def test_llm_error_event_raises_annotation_unavailable():
    class ErroringLLMClient:
        async def stream_chat(self, messages, tools, system_prompt):
            yield LLMEvent(type="error", error="upstream unavailable")

    with pytest.raises(AnnotationUnavailableError):
        await generate_code_annotations("import os\n", "app/main.py", ErroringLLMClient())


@pytest.mark.asyncio
async def test_llm_raising_exception_raises_annotation_unavailable():
    class RaisingLLMClient:
        async def stream_chat(self, messages, tools, system_prompt):
            raise ConnectionError("network is down")
            yield  # pragma: no cover - makes this an async generator

    with pytest.raises(AnnotationUnavailableError):
        await generate_code_annotations("import os\n", "app/main.py", RaisingLLMClient())


@pytest.mark.asyncio
async def test_oversized_file_raises_without_consuming_llm_turns():
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text=VALID_JSON_TEXT)])
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
            for word in VALID_JSON_TEXT.split(" "):
                yield LLMEvent(type="token", token=word + " ")

    content = "import os\nimport sys\n\ndef handler():\n    pass\n"
    await generate_code_annotations(content, "app/main.py", CapturingLLMClient())

    assert len(captured_messages) == 1
    prompt = captured_messages[0][0].content
    assert "app/main.py" in prompt
    assert "1: import os" in prompt
    assert "4: def handler():" in prompt
