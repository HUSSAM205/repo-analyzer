import uuid

import pytest

from app.core.doc_generator import generate_readme
from app.core.llm import FakeLLMClient, LLMEvent, ScriptedTurn
from app.db.models import File


def _file(path: str, content: str) -> File:
    return File(id=uuid.uuid4(), repo_id=uuid.uuid4(), path=path, content=content)


@pytest.mark.asyncio
async def test_generates_readme_from_llm_response():
    files = [_file("package.json", '{"name": "demo"}'), _file("src/index.js", "console.log('hi')")]
    client = FakeLLMClient(turns=[ScriptedTurn(text="# Demo\n\nA demo project.")])

    result = await generate_readme(files, None, client)

    assert result == "# Demo\n\nA demo project."


@pytest.mark.asyncio
async def test_returns_none_for_an_empty_repo():
    client = FakeLLMClient(turns=[])  # would raise if called -- must not be
    result = await generate_readme([], None, client)
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_and_does_not_raise_on_llm_error():
    class ErroringClient:
        async def stream_chat(self, messages, tools, system_prompt):
            yield LLMEvent(type="error", error="rate limited")

    files = [_file("main.py", "print('hi')")]
    result = await generate_readme(files, None, ErroringClient())
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_llm_raises():
    class RaisingClient:
        async def stream_chat(self, messages, tools, system_prompt):
            raise ConnectionError("network down")
            yield  # pragma: no cover

    files = [_file("main.py", "print('hi')")]
    result = await generate_readme(files, None, RaisingClient())
    assert result is None


@pytest.mark.asyncio
async def test_prompt_includes_domain_briefing_and_existing_readme():
    captured = []

    class CapturingClient:
        async def stream_chat(self, messages, tools, system_prompt):
            captured.append(messages[0].content)
            yield LLMEvent(type="token", token="# Doc")
            yield LLMEvent(type="message_done", message=None)

    files = [_file("README.md", "Old readme content here."), _file("main.py", "print('hi')")]
    briefing = {"primary_field": "CLI Tool", "target_audience": "Developers", "tech_stack_badges": ["Python"]}

    await generate_readme(files, briefing, CapturingClient())

    assert len(captured) == 1
    assert "CLI Tool" in captured[0]
    assert "Old readme content here." in captured[0]
    assert "Python" in captured[0]
