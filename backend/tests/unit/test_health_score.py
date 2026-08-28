import json
import uuid

import pytest

from app.core.health_score import compute_health_score
from app.core.llm import FakeLLMClient, LLMEvent, ScriptedTurn
from app.db.models import File


def _file(path: str, content: str = "content") -> File:
    return File(id=uuid.uuid4(), repo_id=uuid.uuid4(), path=path, content=content)


QUALITY_JSON = json.dumps({"quality_score": 80, "commentary": "Clean, consistent code with clear naming."})


@pytest.mark.asyncio
async def test_returns_none_for_an_empty_repo():
    client = FakeLLMClient(turns=[])
    result = await compute_health_score([], client)
    assert result is None


@pytest.mark.asyncio
async def test_falls_back_to_neutral_quality_on_llm_error_but_keeps_real_sub_scores():
    # Regression coverage: documentation/testing/automation never depended
    # on the LLM at all, so an LLM failure must not 503 the whole
    # scorecard -- only the quality sub-score degrades to a clearly-labeled
    # neutral placeholder.
    class ErroringClient:
        async def stream_chat(self, messages, tools, system_prompt):
            yield LLMEvent(type="error", error="rate limited")

    files = [_file("README.md", "x" * 600), _file("tests/test_main.py", "def test_x(): pass")]
    result = await compute_health_score(files, ErroringClient())

    assert result is not None
    assert result["sub_scores"]["quality"] == 50
    assert "temporarily unavailable" in result["commentary"]
    # Real, deterministic sub-scores are unaffected by the LLM failure.
    assert result["sub_scores"]["documentation"] == 100
    assert result["signals"]["has_tests"] is True


@pytest.mark.asyncio
async def test_detects_readme_tests_ci_and_license():
    files = [
        _file("README.md", "x" * 600),
        _file("LICENSE", "MIT"),
        _file(".github/workflows/ci.yml", "name: CI"),
        _file("tests/test_main.py", "def test_x(): pass"),
        _file("src/main.py", "def main(): pass"),
    ]
    client = FakeLLMClient(turns=[ScriptedTurn(text=QUALITY_JSON)])

    result = await compute_health_score(files, client)

    assert result["signals"] == {"has_readme": True, "has_tests": True, "has_ci": True, "has_license": True}
    assert result["sub_scores"]["documentation"] == 100
    assert result["sub_scores"]["automation"] == 70
    assert result["sub_scores"]["quality"] == 80


@pytest.mark.asyncio
async def test_scores_zero_for_missing_signals_on_a_bare_repo():
    files = [_file("main.py")]
    client = FakeLLMClient(turns=[ScriptedTurn(text=QUALITY_JSON)])

    result = await compute_health_score(files, client)

    assert result["signals"] == {"has_readme": False, "has_tests": False, "has_ci": False, "has_license": False}
    assert result["sub_scores"]["documentation"] == 0
    assert result["sub_scores"]["automation"] == 0
    assert result["sub_scores"]["testing"] == 0


@pytest.mark.asyncio
async def test_overall_score_is_the_average_of_sub_scores():
    files = [_file("README.md", "x" * 600), _file("main.py")]
    client = FakeLLMClient(turns=[ScriptedTurn(text=QUALITY_JSON)])

    result = await compute_health_score(files, client)

    expected = round(sum(result["sub_scores"].values()) / 4)
    assert result["overall_score"] == expected


@pytest.mark.asyncio
async def test_falls_back_to_neutral_quality_on_malformed_quality_json():
    client = FakeLLMClient(turns=[ScriptedTurn(text="not json")])
    result = await compute_health_score([_file("main.py")], client)
    assert result is not None
    assert result["sub_scores"]["quality"] == 50


@pytest.mark.asyncio
async def test_clamps_out_of_range_quality_score():
    files = [_file("main.py")]
    client = FakeLLMClient(turns=[ScriptedTurn(text=json.dumps({"quality_score": 150, "commentary": "great"}))])

    result = await compute_health_score(files, client)

    assert result["sub_scores"]["quality"] == 100
