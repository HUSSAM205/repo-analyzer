import json

import pytest

from app.core.chunker import Chunk
from app.core.domain_briefing import generate_domain_briefing
from app.core.ingestion import WalkedFile, WalkResult
from app.core.llm import FakeLLMClient, LLMEvent, Message, ScriptedTurn


def _walk_result(files: list[WalkedFile], chunks: list[Chunk] | None = None) -> WalkResult:
    return WalkResult(
        chunks=chunks or [],
        files=files,
        files_processed=len(files),
        files_skipped=0,
    )


VALID_JSON_TEXT = json.dumps(
    {
        "primary_field": "Full-Stack Web SaaS",
        "target_audience": "Backend engineers building async job pipelines",
        "architecture_overview": "A FastAPI service ingests repos and stores chunks in Postgres.",
        "tech_stack_badges": ["FastAPI", "React"],
    }
)


@pytest.mark.asyncio
async def test_file_type_distribution_is_deterministic_and_grouped():
    files = [
        WalkedFile(path="app/main.py", content=""),
        WalkedFile(path="app/utils.py", content=""),
        WalkedFile(path="frontend/index.tsx", content=""),
        WalkedFile(path="README.md", content=""),
        WalkedFile(path="package.json", content=""),
    ]
    walk_result = _walk_result(files)
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text=VALID_JSON_TEXT)])

    briefing = await generate_domain_briefing(walk_result, llm_client)

    distribution = {entry["label"]: entry["count"] for entry in briefing["file_type_distribution"]}
    assert distribution["Python backend files"] == 2
    assert distribution["TypeScript/React files"] == 1
    assert distribution["Documentation files"] == 1
    assert distribution["JSON/config files"] == 1


@pytest.mark.asyncio
async def test_file_type_distribution_caps_at_top_six_and_sorts_descending():
    files = (
        [WalkedFile(path=f"a{i}.py", content="") for i in range(5)]
        + [WalkedFile(path=f"b{i}.go", content="") for i in range(4)]
        + [WalkedFile(path=f"c{i}.rb", content="") for i in range(3)]
        + [WalkedFile(path=f"d{i}.rs", content="") for i in range(2)]
        + [WalkedFile(path=f"e{i}.php", content="") for i in range(1)]
        + [WalkedFile(path=f"f{i}.sql", content="") for i in range(1)]
        + [WalkedFile(path=f"g{i}.sh", content="") for i in range(1)]
    )
    walk_result = _walk_result(files)
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text=VALID_JSON_TEXT)])

    briefing = await generate_domain_briefing(walk_result, llm_client)

    assert len(briefing["file_type_distribution"]) == 6
    counts = [entry["count"] for entry in briefing["file_type_distribution"]]
    assert counts == sorted(counts, reverse=True)
    assert briefing["file_type_distribution"][0]["label"] == "Python backend files"


@pytest.mark.asyncio
async def test_tech_stack_badges_detected_from_manifest_files_only():
    files = [
        WalkedFile(path="package.json", content="{}"),
        WalkedFile(path="requirements.txt", content=""),
        WalkedFile(path="Dockerfile", content=""),
        WalkedFile(path="src/main.py", content=""),
        # An extension match alone (no exact manifest filename) must not
        # produce a badge -- badge detection is filename-exact, not
        # extension-based.
        WalkedFile(path="notes.json.bak", content=""),
    ]
    walk_result = _walk_result(files)
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text=VALID_JSON_TEXT)])

    briefing = await generate_domain_briefing(walk_result, llm_client)

    assert "Node.js" in briefing["tech_stack_badges"]
    assert "Python" in briefing["tech_stack_badges"]
    assert "Docker" in briefing["tech_stack_badges"]


@pytest.mark.asyncio
async def test_llm_badges_are_merged_deduped_and_capped():
    files = [WalkedFile(path="package.json", content="{}")]
    walk_result = _walk_result(files)
    llm_text = json.dumps(
        {
            "primary_field": "Web",
            "target_audience": "Devs",
            "architecture_overview": "Overview.",
            # "Node.js" duplicates the deterministic badge and must not
            # appear twice; the rest should be merged in, in order.
            "tech_stack_badges": ["Node.js", "React", "Express"],
        }
    )
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text=llm_text)])

    briefing = await generate_domain_briefing(walk_result, llm_client)

    badges = briefing["tech_stack_badges"]
    assert badges.count("Node.js") == 1
    assert "React" in badges
    assert "Express" in badges


@pytest.mark.asyncio
async def test_qualitative_fields_come_from_llm_response():
    files = [WalkedFile(path="main.py", content="")]
    walk_result = _walk_result(files)
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text=VALID_JSON_TEXT)])

    briefing = await generate_domain_briefing(walk_result, llm_client)

    assert briefing["primary_field"] == "Full-Stack Web SaaS"
    assert briefing["target_audience"] == "Backend engineers building async job pipelines"
    assert "FastAPI" in briefing["architecture_overview"]


@pytest.mark.asyncio
async def test_strips_markdown_fences_from_llm_response():
    fenced_text = "```json\n" + VALID_JSON_TEXT + "\n```"
    files = [WalkedFile(path="main.py", content="")]
    walk_result = _walk_result(files)
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text=fenced_text)])

    briefing = await generate_domain_briefing(walk_result, llm_client)

    assert briefing["primary_field"] == "Full-Stack Web SaaS"


@pytest.mark.asyncio
async def test_falls_back_to_deterministic_classification_on_malformed_json():
    # A Python+Docker backend with no frontend hints -- deterministic
    # classification should infer "Backend Web API / Service", not the old
    # unconditional "Unclassified".
    files = [
        WalkedFile(path="requirements.txt", content="fastapi\nuvicorn\n"),
        WalkedFile(path="Dockerfile", content="FROM python:3.12"),
        WalkedFile(path="main.py", content=""),
    ]
    walk_result = _walk_result(files)
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text="this is not valid JSON at all")])

    briefing = await generate_domain_briefing(walk_result, llm_client)

    assert briefing["primary_field"] == "Backend Web API / Service"
    assert briefing["primary_field"] != "Unclassified"
    assert "temporarily unavailable" in briefing["architecture_overview"]
    assert briefing["beginner_summary"]
    # Deterministic parts must still be present even though the LLM part failed.
    assert "Docker" in briefing["tech_stack_badges"]
    assert briefing["file_type_distribution"]


@pytest.mark.asyncio
async def test_falls_back_to_deterministic_classification_when_llm_raises():
    class RaisingLLMClient:
        async def stream_chat(self, messages, tools, system_prompt):
            raise ConnectionError("network is down")
            yield  # pragma: no cover - makes this an async generator

    files = [WalkedFile(path="requirements.txt", content="torch\ntransformers\n"), WalkedFile(path="train.py", content="")]
    walk_result = _walk_result(files)

    briefing = await generate_domain_briefing(walk_result, RaisingLLMClient())

    assert briefing["primary_field"] == "AI / Machine Learning"
    assert briefing["file_type_distribution"]


@pytest.mark.asyncio
async def test_falls_back_to_deterministic_classification_on_llm_error_event():
    class ErroringLLMClient:
        async def stream_chat(self, messages, tools, system_prompt):
            yield LLMEvent(type="error", error="upstream unavailable")

    files = [WalkedFile(path="main.py", content="")]  # no manifest at all
    walk_result = _walk_result(files)

    briefing = await generate_domain_briefing(walk_result, ErroringLLMClient())

    # No recognizable manifest/tech signal at all -- still a real,
    # non-"Unclassified" label rather than nothing.
    assert briefing["primary_field"] == "Software Library / Tool"


@pytest.mark.asyncio
async def test_deterministic_classification_detects_full_stack():
    files = [
        WalkedFile(path="package.json", content='{"dependencies": {"react": "^18", "express": "^4"}}'),
        WalkedFile(path="requirements.txt", content=""),  # forces a Python backend badge too
        WalkedFile(path="src/App.jsx", content="import React from 'react';"),
    ]
    walk_result = _walk_result(files)
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text="not json")])

    briefing = await generate_domain_briefing(walk_result, llm_client)

    assert briefing["primary_field"] == "Full-Stack Web Application"


@pytest.mark.asyncio
async def test_deterministic_classification_detects_devops():
    files = [WalkedFile(path="main.tf", content="resource \"aws_instance\" \"x\" {}\n# uses terraform")]
    walk_result = _walk_result(files)
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text="not json")])

    briefing = await generate_domain_briefing(walk_result, llm_client)

    assert briefing["primary_field"] == "DevOps / Infrastructure"


@pytest.mark.asyncio
async def test_beginner_fields_come_from_llm_response():
    files = [WalkedFile(path="main.py", content="")]
    walk_result = _walk_result(files)
    llm_text = json.dumps({
        "primary_field": "Web",
        "target_audience": "Devs",
        "architecture_overview": "Overview.",
        "tech_stack_badges": [],
        "beginner_summary": "It's like a restaurant: the frontend takes orders, the backend cooks.",
        "tech_stack_explained": [
            {"name": "React", "role": "Builds what you see and click on."},
            {"name": "FastAPI", "role": "The brain/server that handles requests."},
        ],
        "learning_path": [
            {"file_or_topic": "README.md", "why": "Gives you the big picture first."},
            {"file_or_topic": "app/main.py", "why": "This is where the server starts."},
        ],
        "key_takeaways": ["Routes are grouped by feature.", "Config comes from environment variables."],
    })
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text=llm_text)])

    briefing = await generate_domain_briefing(walk_result, llm_client)

    assert briefing["beginner_summary"] == "It's like a restaurant: the frontend takes orders, the backend cooks."
    assert briefing["tech_stack_explained"] == [
        {"name": "React", "role": "Builds what you see and click on."},
        {"name": "FastAPI", "role": "The brain/server that handles requests."},
    ]
    assert briefing["learning_path"] == [
        {"file_or_topic": "README.md", "why": "Gives you the big picture first."},
        {"file_or_topic": "app/main.py", "why": "This is where the server starts."},
    ]
    assert briefing["key_takeaways"] == ["Routes are grouped by feature.", "Config comes from environment variables."]


@pytest.mark.asyncio
async def test_beginner_fields_default_to_empty_when_llm_omits_them():
    # VALID_JSON_TEXT (used throughout this file) predates the beginner
    # fields entirely -- confirms an LLM response missing them degrades
    # gracefully instead of raising or falling back to the *entire* generic
    # briefing (only the three original required keys do that).
    files = [WalkedFile(path="main.py", content="")]
    walk_result = _walk_result(files)
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text=VALID_JSON_TEXT)])

    briefing = await generate_domain_briefing(walk_result, llm_client)

    assert briefing["primary_field"] == "Full-Stack Web SaaS"  # the LLM part still succeeded overall
    assert briefing["beginner_summary"]
    assert briefing["tech_stack_explained"] == []
    assert briefing["learning_path"] == []
    assert briefing["key_takeaways"] == []


@pytest.mark.asyncio
async def test_beginner_fields_ignore_malformed_entries_without_failing():
    files = [WalkedFile(path="main.py", content="")]
    walk_result = _walk_result(files)
    llm_text = json.dumps({
        "primary_field": "Web",
        "target_audience": "Devs",
        "architecture_overview": "Overview.",
        "tech_stack_badges": [],
        "tech_stack_explained": [{"name": "React"}, {"name": "FastAPI", "role": "The brain."}, "not-a-dict"],
        "learning_path": ["not-a-dict", {"file_or_topic": "README.md", "why": "Start here."}],
        "key_takeaways": ["Good one.", 42, None],
    })
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text=llm_text)])

    briefing = await generate_domain_briefing(walk_result, llm_client)

    assert briefing["tech_stack_explained"] == [{"name": "FastAPI", "role": "The brain."}]
    assert briefing["learning_path"] == [{"file_or_topic": "README.md", "why": "Start here."}]
    assert briefing["key_takeaways"] == ["Good one."]


@pytest.mark.asyncio
async def test_falls_back_to_generic_beginner_fields_on_malformed_json():
    files = [WalkedFile(path="main.py", content="")]
    walk_result = _walk_result(files)
    llm_client = FakeLLMClient(turns=[ScriptedTurn(text="not valid JSON")])

    briefing = await generate_domain_briefing(walk_result, llm_client)

    assert briefing["beginner_summary"]
    assert briefing["tech_stack_explained"] == []
    assert briefing["learning_path"] == []
    assert briefing["key_takeaways"] == []


@pytest.mark.asyncio
async def test_prompt_is_compact_and_includes_readme_and_symbols():
    captured_messages: list[list[Message]] = []

    class CapturingLLMClient:
        async def stream_chat(self, messages, tools, system_prompt):
            captured_messages.append(messages)
            assert tools == []
            for word in VALID_JSON_TEXT.split(" "):
                yield LLMEvent(type="token", token=word + " ")

    files = [
        WalkedFile(path="README.md", content="# My Project\nThis does cool things."),
        WalkedFile(path="app/main.py", content="def handler(): pass"),
    ]
    chunks = [
        Chunk(file_path="app/main.py", symbol_name="handler", node_type="function", start_line=1, end_line=1, content="def handler(): pass"),
    ]
    walk_result = _walk_result(files, chunks)

    await generate_domain_briefing(walk_result, CapturingLLMClient())

    assert len(captured_messages) == 1
    prompt = captured_messages[0][0].content
    assert "My Project" in prompt
    assert "handler" in prompt
    assert "app/main.py" in prompt
