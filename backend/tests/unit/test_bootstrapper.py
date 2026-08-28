import json
import uuid

from app.core.bootstrapper import generate_bootstrap
from app.db.models import File


def _file(path: str, content: str) -> File:
    return File(id=uuid.uuid4(), repo_id=uuid.uuid4(), path=path, content=content)


def test_no_recognized_manifest_yields_no_stacks():
    result = generate_bootstrap([_file("README.md", "# hello")])
    assert result["stacks_detected"] == []
    assert result["dockerfile"] == ""
    assert result["docker_compose"] == ""
    assert result["setup_script"] == ""


def test_detects_node_project_and_uses_its_start_script():
    package_json = json.dumps({
        "name": "demo",
        "scripts": {"start": "node server.js", "build": "webpack"},
        "dependencies": {"express": "4.19.2"},
    })
    result = generate_bootstrap([_file("package.json", package_json)])
    assert result["stacks_detected"] == ["node"]
    assert "npm run start" in result["dockerfile"]
    assert "npm run build" in result["dockerfile"]
    assert "node:20-alpine" in result["dockerfile"]
    assert "npm:" not in result["docker_compose"]
    assert "node:" in result["docker_compose"]


def test_node_project_with_lockfile_uses_npm_ci():
    result = generate_bootstrap([
        _file("package.json", json.dumps({"scripts": {}})),
        _file("package-lock.json", "{}"),
    ])
    assert "npm ci" in result["dockerfile"]


def test_reads_node_version_from_engines_field():
    package_json = json.dumps({"engines": {"node": ">=18.0.0"}})
    result = generate_bootstrap([_file("package.json", package_json)])
    assert "node:18-alpine" in result["dockerfile"]


def test_detects_fastapi_project_and_generates_uvicorn_command():
    files = [
        _file("requirements.txt", "fastapi==0.115.0\nuvicorn==0.30.0\n"),
        _file("app/main.py", "app = None"),
    ]
    result = generate_bootstrap(files)
    assert "python" in result["stacks_detected"]
    assert "uvicorn app.main:app --host 0.0.0.0 --port 8000" in result["dockerfile"]
    assert "python:3.12-slim" in result["dockerfile"]


def test_detects_django_project_and_generates_runserver_command():
    files = [_file("requirements.txt", "django==5.0\n"), _file("manage.py", "")]
    result = generate_bootstrap(files)
    assert "manage.py runserver" in result["dockerfile"]


def test_detects_postgres_service_from_asyncpg_dependency():
    files = [_file("requirements.txt", "fastapi\nasyncpg\n")]
    result = generate_bootstrap(files)
    assert "postgres" in result["services_detected"]
    assert "postgres:16-alpine" in result["docker_compose"]


def test_detects_redis_service_from_redis_dependency():
    files = [_file("requirements.txt", "redis\n")]
    result = generate_bootstrap(files)
    assert "redis" in result["services_detected"]
    assert "redis:7-alpine" in result["docker_compose"]


def test_does_not_add_services_that_are_not_actually_used():
    files = [_file("requirements.txt", "fastapi\n")]
    result = generate_bootstrap(files)
    assert result["services_detected"] == []
    assert "postgres" not in result["docker_compose"]
    assert "redis" not in result["docker_compose"]


def test_detects_both_node_and_python_as_two_separate_services_full_stack_repo():
    files = [
        _file("frontend/package.json", json.dumps({"scripts": {"start": "next start"}})),
        _file("backend/requirements.txt", "fastapi\n"),
    ]
    result = generate_bootstrap(files)
    assert set(result["stacks_detected"]) == {"node", "python"}
    assert "node:" in result["dockerfile"]
    assert "python:" in result["dockerfile"]
    assert "target: node" in result["docker_compose"]
    assert "target: python" in result["docker_compose"]


def test_setup_script_is_a_valid_looking_shell_script():
    files = [_file("requirements.txt", "fastapi\n")]
    result = generate_bootstrap(files)
    assert result["setup_script"].startswith("#!/usr/bin/env bash")
    assert "pip install -r requirements.txt" in result["setup_script"]


def test_never_raises_on_malformed_package_json():
    result = generate_bootstrap([_file("package.json", "{not valid json")])
    assert result["stacks_detected"] == ["node"]
    assert "npm start" in result["dockerfile"]
