import json
import uuid

import pytest

from app.core.llm import FakeLLMClient, LLMEvent, ScriptedTurn
from app.core.quiz_generator import generate_quiz
from app.db.models import File


def _file(path: str, content: str = "content") -> File:
    return File(id=uuid.uuid4(), repo_id=uuid.uuid4(), path=path, content=content)


def _valid_question(i: int) -> dict:
    return {
        "question": f"Question {i}?",
        "options": ["A", "B", "C", "D"],
        "correct_index": 1,
        "explanation": f"Explanation {i}.",
    }


VALID_QUIZ_JSON = json.dumps([_valid_question(1), _valid_question(2), _valid_question(3)])


@pytest.mark.asyncio
async def test_generates_and_parses_three_questions():
    files = [_file("main.py", "def main(): pass")]
    client = FakeLLMClient(turns=[ScriptedTurn(text=VALID_QUIZ_JSON)])

    questions = await generate_quiz(files, client)

    assert len(questions) == 3
    assert questions[0]["question"] == "Question 1?"
    assert questions[0]["options"] == ["A", "B", "C", "D"]
    assert questions[0]["correct_index"] == 1


@pytest.mark.asyncio
async def test_returns_none_for_an_empty_repo():
    client = FakeLLMClient(turns=[])
    result = await generate_quiz([], client)
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_on_llm_error():
    class ErroringClient:
        async def stream_chat(self, messages, tools, system_prompt):
            yield LLMEvent(type="error", error="rate limited")

    result = await generate_quiz([_file("main.py")], ErroringClient())
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_on_malformed_json():
    client = FakeLLMClient(turns=[ScriptedTurn(text="not json")])
    result = await generate_quiz([_file("main.py")], client)
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_fewer_than_three_valid_questions_survive_filtering():
    # A quiz with fewer than 3 questions is worse than no quiz at all --
    # unlike security_scanner's findings list, a partial quiz isn't useful.
    quiz_json = json.dumps([
        _valid_question(1),
        {"question": "Bad", "options": ["only two"], "correct_index": 0, "explanation": "x"},  # wrong option count
        {"question": "Bad2", "options": ["A", "B", "C", "D"], "correct_index": 9, "explanation": "x"},  # out of range
    ])
    client = FakeLLMClient(turns=[ScriptedTurn(text=quiz_json)])

    result = await generate_quiz([_file("main.py")], client)

    assert result is None


@pytest.mark.asyncio
async def test_drops_malformed_questions_but_keeps_result_when_still_three_valid():
    quiz_json = json.dumps([
        _valid_question(1),
        _valid_question(2),
        _valid_question(3),
        {"question": "Extra bad one", "options": ["only two"], "correct_index": 0, "explanation": "x"},
    ])
    client = FakeLLMClient(turns=[ScriptedTurn(text=quiz_json)])

    result = await generate_quiz([_file("main.py")], client)

    assert len(result) == 3
    assert all(q["question"].startswith("Question") for q in result)


@pytest.mark.asyncio
async def test_returns_none_when_llm_raises():
    class RaisingClient:
        async def stream_chat(self, messages, tools, system_prompt):
            raise ConnectionError("network down")
            yield  # pragma: no cover

    result = await generate_quiz([_file("main.py")], RaisingClient())
    assert result is None
