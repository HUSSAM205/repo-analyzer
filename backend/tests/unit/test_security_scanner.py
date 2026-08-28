import json
import uuid

import pytest

from app.core.llm import FakeLLMClient, LLMEvent, ScriptedTurn
from app.core.security_scanner import scan_for_issues
from app.db.models import File


def _file(path: str, content: str) -> File:
    return File(id=uuid.uuid4(), repo_id=uuid.uuid4(), path=path, content=content)


VALID_FINDINGS_JSON = json.dumps([
    {
        "severity": "high",
        "category": "security",
        "file": "app/auth.py",
        "line": 42,
        "title": "Hardcoded secret key",
        "description": "The JWT secret is hardcoded rather than read from an environment variable.",
    }
])


@pytest.mark.asyncio
async def test_returns_parsed_findings_from_llm_response():
    files = [_file("app/auth.py", "SECRET = 'hardcoded'")]
    client = FakeLLMClient(turns=[ScriptedTurn(text=VALID_FINDINGS_JSON)])

    findings = await scan_for_issues(files, client)

    assert findings == [{
        "severity": "high",
        "category": "security",
        "file": "app/auth.py",
        "line": 42,
        "title": "Hardcoded secret key",
        "description": "The JWT secret is hardcoded rather than read from an environment variable.",
    }]


@pytest.mark.asyncio
async def test_empty_array_is_a_valid_cacheable_result_not_a_failure():
    files = [_file("main.py", "print('clean code')")]
    client = FakeLLMClient(turns=[ScriptedTurn(text="[]")])

    findings = await scan_for_issues(files, client)

    assert findings == []


@pytest.mark.asyncio
async def test_returns_none_for_an_empty_repo():
    client = FakeLLMClient(turns=[])
    findings = await scan_for_issues([], client)
    assert findings is None


@pytest.mark.asyncio
async def test_returns_none_on_llm_error():
    class ErroringClient:
        async def stream_chat(self, messages, tools, system_prompt):
            yield LLMEvent(type="error", error="rate limited")

    files = [_file("main.py", "code")]
    findings = await scan_for_issues(files, ErroringClient())
    assert findings is None


@pytest.mark.asyncio
async def test_returns_none_on_malformed_json():
    files = [_file("main.py", "code")]
    client = FakeLLMClient(turns=[ScriptedTurn(text="not json at all")])
    findings = await scan_for_issues(files, client)
    assert findings is None


@pytest.mark.asyncio
async def test_drops_malformed_individual_findings_without_failing_the_whole_scan():
    findings_json = json.dumps([
        {"severity": "high", "category": "security", "file": "a.py", "line": 1, "title": "Real issue", "description": "A real one."},
        {"severity": "not-a-real-severity", "category": "security", "file": "b.py", "title": "Bad severity", "description": "x"},
        {"severity": "low", "category": "bug", "file": "c.py", "title": "Missing description"},
        "not-a-dict",
    ])
    files = [_file("main.py", "code")]
    client = FakeLLMClient(turns=[ScriptedTurn(text=findings_json)])

    findings = await scan_for_issues(files, client)

    assert len(findings) == 1
    assert findings[0]["title"] == "Real issue"


@pytest.mark.asyncio
async def test_skips_lock_and_binary_like_files_from_the_sample():
    captured = []

    class CapturingClient:
        async def stream_chat(self, messages, tools, system_prompt):
            captured.append(messages[0].content)
            yield LLMEvent(type="token", token="[]")

    files = [
        _file("package-lock.json", "x" * 100),
        _file("app.min.js", "y" * 100),
        _file("main.py", "print('real source')"),
    ]
    await scan_for_issues(files, CapturingClient())

    assert "real source" in captured[0]
    assert "package-lock.json" not in captured[0]
    assert "app.min.js" not in captured[0]
