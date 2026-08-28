import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import File, Repo, RepoStatus
from app.db.session import async_session_maker
from app.main import app

pytestmark = pytest.mark.integration

VALID_FINDINGS_JSON = json.dumps([
    {
        "severity": "medium",
        "category": "bug",
        "file": "main.py",
        "line": 3,
        "title": "Unhandled exception",
        "description": "This call can raise but nothing catches it.",
    }
])
VALID_QUALITY_JSON = json.dumps({"quality_score": 72, "commentary": "Reasonably consistent, could use more tests."})


def _quiz_question(i: int) -> dict:
    return {
        "question": f"Question {i}?",
        "options": ["A", "B", "C", "D"],
        "correct_index": 1,
        "explanation": f"Explanation {i}.",
    }


VALID_QUIZ_JSON = json.dumps([_quiz_question(1), _quiz_question(2), _quiz_question(3)])


async def _register_and_login(client: AsyncClient) -> str:
    email = f"flagship-{uuid.uuid4()}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
    login_resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
    return login_resp.json()["access_token"]


async def _setup_repo(client: AsyncClient, status: RepoStatus = RepoStatus.READY) -> tuple[str, dict]:
    token = await _register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    me_resp = await client.get("/api/v1/auth/me", headers=headers)
    user_id = me_resp.json()["id"]

    async with async_session_maker() as db:
        repo = Repo(
            user_id=user_id, url=f"https://github.com/example/flagship-{uuid.uuid4()}", name="flagshiprepo",
            status=status,
        )
        db.add(repo)
        await db.flush()
        if status == RepoStatus.READY:
            db.add(File(repo_id=repo.id, path="main.py", content="def main():\n    risky_call()\n"))
        await db.commit()
        repo_id = str(repo.id)

    return repo_id, headers


@pytest.mark.asyncio
async def test_readme_generates_and_caches(monkeypatch):
    from app.core.llm import FakeLLMClient, ScriptedTurn

    monkeypatch.setattr(
        "app.api.routes.flagship.get_llm_client",
        lambda: FakeLLMClient(turns=[ScriptedTurn(text="# flagshiprepo\n\nA demo project.")]),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers = await _setup_repo(client)

        resp = await client.get(f"/api/v1/repos/{repo_id}/readme", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["content"] == "# flagshiprepo\n\nA demo project."

        async with async_session_maker() as db:
            repo = await db.get(Repo, uuid.UUID(repo_id))
            assert repo.readme_doc == "# flagshiprepo\n\nA demo project."


@pytest.mark.asyncio
async def test_readme_cache_hit_skips_llm_call(monkeypatch):
    class ExplodingLLMClient:
        async def stream_chat(self, messages, tools, system_prompt):
            raise AssertionError("LLM must not be called on a cache hit")
            yield  # pragma: no cover

    monkeypatch.setattr("app.api.routes.flagship.get_llm_client", lambda: ExplodingLLMClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers = await _setup_repo(client)

        async with async_session_maker() as db:
            repo = await db.get(Repo, uuid.UUID(repo_id))
            repo.readme_doc = "# Already generated"
            await db.commit()

        resp = await client.get(f"/api/v1/repos/{repo_id}/readme", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["content"] == "# Already generated"


@pytest.mark.asyncio
async def test_readme_returns_409_when_repo_not_ready():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers = await _setup_repo(client, status=RepoStatus.PENDING)
        resp = await client.get(f"/api/v1/repos/{repo_id}/readme", headers=headers)
        assert resp.status_code == 409


@pytest.mark.asyncio
async def test_readme_falls_back_to_deterministic_doc_when_llm_unavailable(monkeypatch):
    from app.core.llm import LLMEvent

    class ErroringClient:
        async def stream_chat(self, messages, tools, system_prompt):
            yield LLMEvent(type="error", error="rate limited")

    monkeypatch.setattr("app.api.routes.flagship.get_llm_client", lambda: ErroringClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers = await _setup_repo(client)

        # Never a 503 -- the deterministic fallback (doc_generator.py's
        # build_deterministic_readme) always produces a real document.
        resp = await client.get(f"/api/v1/repos/{repo_id}/readme", headers=headers)
        assert resp.status_code == 200
        assert "temporarily unavailable" in resp.json()["content"]

        async with async_session_maker() as db:
            repo = await db.get(Repo, uuid.UUID(repo_id))
            # The fallback result is cached exactly like a real one.
            assert repo.readme_doc is not None


@pytest.mark.asyncio
async def test_security_scan_generates_and_caches(monkeypatch):
    from app.core.llm import FakeLLMClient, ScriptedTurn

    monkeypatch.setattr(
        "app.api.routes.flagship.get_llm_client",
        lambda: FakeLLMClient(turns=[ScriptedTurn(text=VALID_FINDINGS_JSON)]),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers = await _setup_repo(client)

        resp = await client.get(f"/api/v1/repos/{repo_id}/security-scan", headers=headers)
        assert resp.status_code == 200
        findings = resp.json()["findings"]
        assert len(findings) == 1
        assert findings[0]["title"] == "Unhandled exception"

        async with async_session_maker() as db:
            repo = await db.get(Repo, uuid.UUID(repo_id))
            assert repo.security_scan is not None


@pytest.mark.asyncio
async def test_security_scan_falls_back_to_deterministic_secret_scan_when_llm_unavailable(monkeypatch):
    from app.core.llm import LLMEvent

    class ErroringClient:
        async def stream_chat(self, messages, tools, system_prompt):
            yield LLMEvent(type="error", error="rate limited")

    monkeypatch.setattr("app.api.routes.flagship.get_llm_client", lambda: ErroringClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers = await _setup_repo(client)

        # Never a 503 -- the deterministic fallback (security_scanner.py's
        # build_deterministic_findings) always returns a valid (possibly
        # empty) findings list.
        resp = await client.get(f"/api/v1/repos/{repo_id}/security-scan", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["findings"] == []  # the test file has no secrets

        async with async_session_maker() as db:
            repo = await db.get(Repo, uuid.UUID(repo_id))
            # The fallback (even an empty list) is cached exactly like a
            # real result.
            assert repo.security_scan is not None


@pytest.mark.asyncio
async def test_health_score_generates_and_caches(monkeypatch):
    from app.core.llm import FakeLLMClient, ScriptedTurn

    monkeypatch.setattr(
        "app.api.routes.flagship.get_llm_client",
        lambda: FakeLLMClient(turns=[ScriptedTurn(text=VALID_QUALITY_JSON)]),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers = await _setup_repo(client)

        resp = await client.get(f"/api/v1/repos/{repo_id}/health-score", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["sub_scores"]["quality"] == 72
        assert 0 <= body["overall_score"] <= 100

        async with async_session_maker() as db:
            repo = await db.get(Repo, uuid.UUID(repo_id))
            assert repo.health_score is not None


@pytest.mark.asyncio
async def test_quiz_generates_and_caches(monkeypatch):
    from app.core.llm import FakeLLMClient, ScriptedTurn

    monkeypatch.setattr(
        "app.api.routes.flagship.get_llm_client",
        lambda: FakeLLMClient(turns=[ScriptedTurn(text=VALID_QUIZ_JSON)]),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers = await _setup_repo(client)

        resp = await client.get(f"/api/v1/repos/{repo_id}/quiz", headers=headers)
        assert resp.status_code == 200
        questions = resp.json()["questions"]
        assert len(questions) == 3
        assert questions[0]["options"] == ["A", "B", "C", "D"]

        async with async_session_maker() as db:
            repo = await db.get(Repo, uuid.UUID(repo_id))
            assert repo.quiz is not None


@pytest.mark.asyncio
async def test_quiz_cache_hit_skips_llm_call(monkeypatch):
    class ExplodingLLMClient:
        async def stream_chat(self, messages, tools, system_prompt):
            raise AssertionError("LLM must not be called on a cache hit")
            yield  # pragma: no cover

    monkeypatch.setattr("app.api.routes.flagship.get_llm_client", lambda: ExplodingLLMClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers = await _setup_repo(client)

        async with async_session_maker() as db:
            repo = await db.get(Repo, uuid.UUID(repo_id))
            repo.quiz = [_quiz_question(1), _quiz_question(2), _quiz_question(3)]
            await db.commit()

        resp = await client.get(f"/api/v1/repos/{repo_id}/quiz", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()["questions"]) == 3


@pytest.mark.asyncio
async def test_quiz_falls_back_to_deterministic_quiz_on_a_partial_ai_quiz(monkeypatch):
    from app.core.llm import FakeLLMClient, ScriptedTurn

    # Only 2 valid questions -- quiz_generator.generate_quiz treats this as
    # a failure (None), same as a malformed response, which the deterministic
    # fallback (quiz_generator.build_deterministic_quiz) then covers instead
    # of a 503.
    incomplete_quiz = json.dumps([_quiz_question(1), _quiz_question(2)])
    monkeypatch.setattr(
        "app.api.routes.flagship.get_llm_client",
        lambda: FakeLLMClient(turns=[ScriptedTurn(text=incomplete_quiz)]),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers = await _setup_repo(client)

        resp = await client.get(f"/api/v1/repos/{repo_id}/quiz", headers=headers)
        assert resp.status_code == 200
        questions = resp.json()["questions"]
        assert len(questions) == 3
        assert all(len(q["options"]) == 4 for q in questions)

        async with async_session_maker() as db:
            repo = await db.get(Repo, uuid.UUID(repo_id))
            # The fallback result is cached exactly like a real one.
            assert repo.quiz is not None


VALID_FLOW_MAP_TEXT = "flowchart TD\n  Client --> Router[main.py]\n  Router --> DB[(Postgres)]"
VALID_TECH_DEBT_JSON = json.dumps({
    "summary": "Some duplicated validation logic.",
    "items": [
        {
            "file": "main.py",
            "issue": "Duplicated validation",
            "estimated_hours": 2,
            "before_snippet": "if x: pass",
            "after_snippet": "def check(x): return x",
            "explanation": "Deduplicates the check.",
        }
    ],
})


@pytest.mark.asyncio
async def test_flow_map_generates_and_caches(monkeypatch):
    from app.core.llm import FakeLLMClient, ScriptedTurn

    monkeypatch.setattr(
        "app.api.routes.flagship.get_llm_client",
        lambda: FakeLLMClient(turns=[ScriptedTurn(text=VALID_FLOW_MAP_TEXT)]),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers = await _setup_repo(client)

        resp = await client.get(f"/api/v1/repos/{repo_id}/flow-map", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["diagram"].startswith("flowchart TD")

        async with async_session_maker() as db:
            repo = await db.get(Repo, uuid.UUID(repo_id))
            assert repo.flow_map is not None


@pytest.mark.asyncio
async def test_flow_map_cache_hit_skips_llm_call(monkeypatch):
    class ExplodingLLMClient:
        async def stream_chat(self, messages, tools, system_prompt):
            raise AssertionError("LLM must not be called on a cache hit")
            yield  # pragma: no cover

    monkeypatch.setattr("app.api.routes.flagship.get_llm_client", lambda: ExplodingLLMClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers = await _setup_repo(client)

        async with async_session_maker() as db:
            repo = await db.get(Repo, uuid.UUID(repo_id))
            repo.flow_map = VALID_FLOW_MAP_TEXT
            await db.commit()

        resp = await client.get(f"/api/v1/repos/{repo_id}/flow-map", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["diagram"] == VALID_FLOW_MAP_TEXT


@pytest.mark.asyncio
async def test_tech_debt_generates_and_caches(monkeypatch):
    from app.core.llm import FakeLLMClient, ScriptedTurn

    monkeypatch.setattr(
        "app.api.routes.flagship.get_llm_client",
        lambda: FakeLLMClient(turns=[ScriptedTurn(text=VALID_TECH_DEBT_JSON)]),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers = await _setup_repo(client)

        resp = await client.get(f"/api/v1/repos/{repo_id}/tech-debt", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["estimated_debt_hours"] == 2.0
        assert len(body["items"]) == 1

        async with async_session_maker() as db:
            repo = await db.get(Repo, uuid.UUID(repo_id))
            assert repo.tech_debt is not None


@pytest.mark.asyncio
async def test_tech_debt_cache_hit_skips_llm_call(monkeypatch):
    class ExplodingLLMClient:
        async def stream_chat(self, messages, tools, system_prompt):
            raise AssertionError("LLM must not be called on a cache hit")
            yield  # pragma: no cover

    monkeypatch.setattr("app.api.routes.flagship.get_llm_client", lambda: ExplodingLLMClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers = await _setup_repo(client)

        async with async_session_maker() as db:
            repo = await db.get(Repo, uuid.UUID(repo_id))
            repo.tech_debt = {"summary": "cached", "items": [], "estimated_debt_hours": 0.0}
            await db.commit()

        resp = await client.get(f"/api/v1/repos/{repo_id}/tech-debt", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["summary"] == "cached"


@pytest.mark.asyncio
async def test_flow_map_falls_back_to_deterministic_diagram_when_llm_unavailable(monkeypatch):
    from app.core.llm import LLMEvent

    class ErroringClient:
        async def stream_chat(self, messages, tools, system_prompt):
            yield LLMEvent(type="error", error="rate limited")

    monkeypatch.setattr("app.api.routes.flagship.get_llm_client", lambda: ErroringClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers = await _setup_repo(client)

        # Never a 503 -- the deterministic fallback (flow_map.py's
        # build_deterministic_flow_map) always produces a valid diagram.
        resp = await client.get(f"/api/v1/repos/{repo_id}/flow-map", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["diagram"].startswith("flowchart TD")

        async with async_session_maker() as db:
            repo = await db.get(Repo, uuid.UUID(repo_id))
            # The fallback result is cached exactly like a real one.
            assert repo.flow_map is not None


@pytest.mark.asyncio
async def test_tech_debt_falls_back_to_deterministic_report_when_llm_unavailable(monkeypatch):
    from app.core.llm import LLMEvent

    class ErroringClient:
        async def stream_chat(self, messages, tools, system_prompt):
            yield LLMEvent(type="error", error="rate limited")

    monkeypatch.setattr("app.api.routes.flagship.get_llm_client", lambda: ErroringClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers = await _setup_repo(client)

        resp = await client.get(f"/api/v1/repos/{repo_id}/tech-debt", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "temporarily unavailable" in body["summary"]
        # The single test file has no tests/CI, and both are cheap
        # deterministic signals -- both should surface as items.
        issues = {item["issue"] for item in body["items"]}
        assert any("No test files detected" in i for i in issues)
        assert any("No CI configuration detected" in i for i in issues)


@pytest.mark.asyncio
async def test_compliance_scan_generates_and_caches_without_any_llm_call(monkeypatch):
    class ExplodingLLMClient:
        async def stream_chat(self, messages, tools, system_prompt):
            raise AssertionError("Compliance scan must never call the LLM")
            yield  # pragma: no cover

    monkeypatch.setattr("app.api.routes.flagship.get_llm_client", lambda: ExplodingLLMClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers = await _setup_repo(client)

        resp = await client.get(f"/api/v1/repos/{repo_id}/compliance-scan", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["overall_risk"] == "low"
        assert body["secret_findings"] == []
        assert body["dangerous_pattern_findings"] == []

        async with async_session_maker() as db:
            repo = await db.get(Repo, uuid.UUID(repo_id))
            assert repo.compliance_scan is not None


@pytest.mark.asyncio
async def test_route_explorer_extracts_routes_without_any_llm_call(monkeypatch):
    class ExplodingLLMClient:
        async def stream_chat(self, messages, tools, system_prompt):
            raise AssertionError("Route explorer must never call the LLM")
            yield  # pragma: no cover

    monkeypatch.setattr("app.api.routes.flagship.get_llm_client", lambda: ExplodingLLMClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        me_resp = await client.get("/api/v1/auth/me", headers=headers)
        user_id = me_resp.json()["id"]

        async with async_session_maker() as db:
            repo = Repo(
                user_id=user_id, url=f"https://github.com/example/routes-{uuid.uuid4()}", name="routerepo",
                status=RepoStatus.READY,
            )
            db.add(repo)
            await db.flush()
            db.add(File(
                repo_id=repo.id, path="app/api/routes/items.py",
                content=(
                    'router = APIRouter(prefix="/api/v1/items")\n\n'
                    '@router.get("/{item_id}")\n'
                    "async def get_item(item_id: UUID, current_user: Annotated[User, Depends(get_current_user)]):\n"
                    "    ...\n"
                ),
            ))
            await db.commit()
            repo_id = str(repo.id)

        resp = await client.get(f"/api/v1/repos/{repo_id}/routes", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["frameworks_detected"] == ["fastapi"]
        [route] = body["routes"]
        assert route["method"] == "GET"
        assert route["path"] == "/api/v1/items/{item_id}"
        assert route["auth_required"] is True


@pytest.mark.asyncio
async def test_route_explorer_returns_an_empty_list_for_a_repo_with_no_recognized_routes():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers = await _setup_repo(client)

        resp = await client.get(f"/api/v1/repos/{repo_id}/routes", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["routes"] == []
        assert resp.json()["frameworks_detected"] == []


@pytest.mark.asyncio
async def test_module_map_generates_without_any_llm_call(monkeypatch):
    class ExplodingLLMClient:
        async def stream_chat(self, messages, tools, system_prompt):
            raise AssertionError("Module map must never call the LLM")
            yield  # pragma: no cover

    monkeypatch.setattr("app.api.routes.flagship.get_llm_client", lambda: ExplodingLLMClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers = await _setup_repo(client)

        resp = await client.get(f"/api/v1/repos/{repo_id}/module-map", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["diagram"].startswith("flowchart TD")
        assert body["file_count"] == 1


@pytest.mark.asyncio
async def test_bootstrap_generates_dockerfile_without_any_llm_call(monkeypatch):
    class ExplodingLLMClient:
        async def stream_chat(self, messages, tools, system_prompt):
            raise AssertionError("Bootstrap must never call the LLM")
            yield  # pragma: no cover

    monkeypatch.setattr("app.api.routes.flagship.get_llm_client", lambda: ExplodingLLMClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        me_resp = await client.get("/api/v1/auth/me", headers=headers)
        user_id = me_resp.json()["id"]

        async with async_session_maker() as db:
            repo = Repo(
                user_id=user_id, url=f"https://github.com/example/bootstrap-{uuid.uuid4()}", name="bootstraprepo",
                status=RepoStatus.READY,
            )
            db.add(repo)
            await db.flush()
            db.add(File(repo_id=repo.id, path="requirements.txt", content="fastapi\nuvicorn\n"))
            await db.commit()
            repo_id = str(repo.id)

        resp = await client.get(f"/api/v1/repos/{repo_id}/bootstrap", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["stacks_detected"] == ["python"]
        assert "FROM python:" in body["dockerfile"]
        assert body["setup_script"].startswith("#!/usr/bin/env bash")


@pytest.mark.asyncio
async def test_complexity_radar_finds_hotspots_without_any_llm_call(monkeypatch):
    class ExplodingLLMClient:
        async def stream_chat(self, messages, tools, system_prompt):
            raise AssertionError("Complexity radar must never call the LLM")
            yield  # pragma: no cover

    monkeypatch.setattr("app.api.routes.flagship.get_llm_client", lambda: ExplodingLLMClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        me_resp = await client.get("/api/v1/auth/me", headers=headers)
        user_id = me_resp.json()["id"]

        async with async_session_maker() as db:
            repo = Repo(
                user_id=user_id, url=f"https://github.com/example/complexity-{uuid.uuid4()}", name="complexrepo",
                status=RepoStatus.READY,
            )
            db.add(repo)
            await db.flush()
            db.add(File(
                repo_id=repo.id, path="app.py",
                content="def branchy(x):\n    if x:\n        if x > 1:\n            return 1\n    return 0\n",
            ))
            await db.commit()
            repo_id = str(repo.id)

        resp = await client.get(f"/api/v1/repos/{repo_id}/complexity", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["functions_analyzed"] == 1
        [hotspot] = body["hotspots"]
        assert hotspot["function"] == "branchy"
        assert hotspot["complexity"] == 3


@pytest.mark.asyncio
async def test_compliance_scan_tolerates_a_cached_scan_from_before_dangerous_pattern_findings_existed():
    # repo.compliance_scan is cached permanently once computed (see
    # get_compliance_scan) -- a repo analyzed before this field was added
    # has an old-shaped dict in the DB with no such key at all. The
    # response schema must still validate it (via the field's default),
    # not 500 on every repo analyzed before this feature shipped.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, headers = await _setup_repo(client)

        async with async_session_maker() as db:
            repo = await db.get(Repo, uuid.UUID(repo_id))
            repo.compliance_scan = {
                "overall_risk": "low",
                "license_findings": [],
                "secret_findings": [],
                "disclaimer": "old disclaimer text",
            }
            await db.commit()

        resp = await client.get(f"/api/v1/repos/{repo_id}/compliance-scan", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["dangerous_pattern_findings"] == []


@pytest.mark.asyncio
async def test_flagship_endpoints_accessible_by_other_users(monkeypatch):
    from app.core.llm import FakeLLMClient, ScriptedTurn

    monkeypatch.setattr(
        "app.api.routes.flagship.get_llm_client",
        lambda: FakeLLMClient(turns=[ScriptedTurn(text="# Doc")]),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        repo_id, _owner_headers = await _setup_repo(client)

        other_token = await _register_and_login(client)
        other_headers = {"Authorization": f"Bearer {other_token}"}

        resp = await client.get(f"/api/v1/repos/{repo_id}/readme", headers=other_headers)
        assert resp.status_code == 200
