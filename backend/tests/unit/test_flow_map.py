import uuid

import pytest

from app.core.flow_map import generate_flow_map
from app.core.llm import FakeLLMClient, LLMEvent, ScriptedTurn
from app.db.models import File

VALID_DIAGRAM = "flowchart TD\n  Client --> Router[api/routes.py]\n  Router --> DB[(Postgres)]"


def _file(path: str, content: str = "content") -> File:
    return File(id=uuid.uuid4(), repo_id=uuid.uuid4(), path=path, content=content)


@pytest.mark.asyncio
async def test_generates_and_returns_valid_diagram():
    files = [_file("app/routes.py", "@app.get('/x')\ndef handler(): pass")]
    client = FakeLLMClient(turns=[ScriptedTurn(text=VALID_DIAGRAM)])

    diagram = await generate_flow_map(files, client)

    assert diagram is not None
    assert diagram.startswith("flowchart TD")


@pytest.mark.asyncio
async def test_strips_markdown_fences():
    fenced = f"```mermaid\n{VALID_DIAGRAM}\n```"
    client = FakeLLMClient(turns=[ScriptedTurn(text=fenced)])

    diagram = await generate_flow_map([_file("main.py")], client)

    assert diagram == VALID_DIAGRAM


@pytest.mark.asyncio
async def test_returns_none_for_an_empty_repo():
    result = await generate_flow_map([], FakeLLMClient(turns=[]))
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_response_is_not_a_recognized_diagram_type():
    client = FakeLLMClient(turns=[ScriptedTurn(text="Sorry, I can't help with that.")])
    result = await generate_flow_map([_file("main.py")], client)
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_on_llm_error():
    class ErroringClient:
        async def stream_chat(self, messages, tools, system_prompt):
            yield LLMEvent(type="error", error="rate limited")

    result = await generate_flow_map([_file("main.py")], ErroringClient())
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_llm_raises():
    class RaisingClient:
        async def stream_chat(self, messages, tools, system_prompt):
            raise ConnectionError("network down")
            yield  # pragma: no cover

    result = await generate_flow_map([_file("main.py")], RaisingClient())
    assert result is None


@pytest.mark.asyncio
async def test_samples_layer_relevant_files_first():
    from app.core.flow_map import _pick_sample_files

    files = [
        _file("misc/random_notes.txt"),
        _file("app/controllers/user_controller.py"),
        _file("app/services/user_service.py"),
    ]
    picked = _pick_sample_files(files)
    picked_paths = [f.path for f in picked]
    assert picked_paths[0] in {"app/controllers/user_controller.py", "app/services/user_service.py"}
