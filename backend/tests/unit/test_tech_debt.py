import json
import uuid

import pytest

from app.core.llm import FakeLLMClient, LLMEvent, ScriptedTurn
from app.core.tech_debt import generate_tech_debt_report
from app.db.models import File


def _file(path: str, content: str = "content") -> File:
    return File(id=uuid.uuid4(), repo_id=uuid.uuid4(), path=path, content=content)


def _item(hours: float) -> dict:
    return {
        "file": "main.py",
        "issue": "Duplicated validation logic",
        "estimated_hours": hours,
        "before_snippet": "if x: pass\nif x: pass",
        "after_snippet": "def check(x): return x",
        "explanation": "Deduplicates the check into one function.",
    }


@pytest.mark.asyncio
async def test_generates_report_and_sums_hours_from_items():
    body = json.dumps({"summary": "Some debt found.", "items": [_item(2.5), _item(1.0)]})
    client = FakeLLMClient(turns=[ScriptedTurn(text=body)])

    report = await generate_tech_debt_report([_file("main.py")], client)

    assert report is not None
    assert report["summary"] == "Some debt found."
    assert len(report["items"]) == 2
    # Deliberately computed from the items themselves, not trusted from a
    # separate LLM-stated total -- see tech_debt.py's _parse_response.
    assert report["estimated_debt_hours"] == 3.5


@pytest.mark.asyncio
async def test_empty_items_is_a_valid_clean_result():
    body = json.dumps({"summary": "This codebase looks clean.", "items": []})
    client = FakeLLMClient(turns=[ScriptedTurn(text=body)])

    report = await generate_tech_debt_report([_file("main.py")], client)

    assert report == {"summary": "This codebase looks clean.", "items": [], "estimated_debt_hours": 0.0}


@pytest.mark.asyncio
async def test_drops_malformed_items_but_keeps_the_valid_ones():
    body = json.dumps({
        "summary": "Mixed.",
        "items": [_item(1.0), {"file": "x.py", "issue": "missing fields"}],
    })
    client = FakeLLMClient(turns=[ScriptedTurn(text=body)])

    report = await generate_tech_debt_report([_file("main.py")], client)

    assert len(report["items"]) == 1
    assert report["estimated_debt_hours"] == 1.0


@pytest.mark.asyncio
async def test_returns_none_for_an_empty_repo():
    result = await generate_tech_debt_report([], FakeLLMClient(turns=[]))
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_summary_key_is_missing():
    client = FakeLLMClient(turns=[ScriptedTurn(text=json.dumps({"items": []}))])
    result = await generate_tech_debt_report([_file("main.py")], client)
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_on_llm_error():
    class ErroringClient:
        async def stream_chat(self, messages, tools, system_prompt):
            yield LLMEvent(type="error", error="rate limited")

    result = await generate_tech_debt_report([_file("main.py")], ErroringClient())
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_llm_raises():
    class RaisingClient:
        async def stream_chat(self, messages, tools, system_prompt):
            raise ConnectionError("network down")
            yield  # pragma: no cover

    result = await generate_tech_debt_report([_file("main.py")], RaisingClient())
    assert result is None
