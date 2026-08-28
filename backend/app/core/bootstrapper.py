"""Deterministic Dockerfile / docker-compose.yml / setup-script generation
from a repo's own package manifests -- zero LLM tokens, same reasoning as
compliance_scanner.py and route_explorer.py: a build/run command is either
right or it silently doesn't work, so a template assembled from what the
manifest actually declares is more trustworthy than a model's plausible
guess at "the Dockerfile this project probably needs."

Deliberately narrow: detects Node (package.json) and Python (requirements.txt
or pyproject.toml) stacks specifically, and Postgres/Redis as *services* only
from a small set of very common driver package names -- not a general
polyglot build-system inference engine. A repo using neither ecosystem's
usual manifest, or a less common one (Poetry's own lockfile-only setup,
Go's go.mod, etc.), gets an honest "couldn't detect a supported stack"
result rather than a guessed-wrong template.
"""

import json
import re

from app.db.models import File

_NODE_START_SCRIPT_CANDIDATES = ("start", "dev")
_PYTHON_ENTRYPOINT_CANDIDATES = (
    ("app/main.py", "app.main:app", "uvicorn"),
    ("main.py", "main:app", "uvicorn"),
    ("manage.py", None, "django"),
)

# name -> compose service block (Postgres/Redis are added only when a
# familiar driver package name for that service is actually declared --
# guessing service dependencies a project doesn't use would produce a
# compose file that doesn't reflect the real app.
_SERVICE_MARKER_PACKAGES: dict[str, set[str]] = {
    "postgres": {"psycopg2", "psycopg2-binary", "asyncpg", "pg", "sequelize", "prisma"},
    "redis": {"redis", "ioredis", "aioredis"},
}


def _detect_node(files: dict[str, str]) -> dict | None:
    package_json = files.get("package.json")
    if package_json is None:
        return None
    try:
        data = json.loads(package_json)
    except Exception:
        data = {}
    scripts = data.get("scripts") if isinstance(data.get("scripts"), dict) else {}
    deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
    start_script = next((s for s in _NODE_START_SCRIPT_CANDIDATES if s in scripts), None)
    node_version = "20"
    engines = data.get("engines")
    if isinstance(engines, dict) and isinstance(engines.get("node"), str):
        digits = re.search(r"\d+", engines["node"])
        if digits:
            node_version = digits.group(0)
    return {
        "ecosystem": "node",
        "node_version": node_version,
        "start_command": f"npm run {start_script}" if start_script else "npm start",
        "install_command": "npm ci" if "package-lock.json" in files else "npm install",
        "build_command": "npm run build" if "build" in scripts else None,
        "port": 3000,
        "declared_packages": set(deps.keys()),
    }


def _detect_python(files: dict[str, str], all_paths: set[str]) -> dict | None:
    has_requirements = "requirements.txt" in files
    has_pyproject = "pyproject.toml" in files
    if not has_requirements and not has_pyproject:
        return None

    declared_packages: set[str] = set()
    if has_requirements:
        for line in files["requirements.txt"].splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith(("#", "-")):
                name = re.match(r"^[A-Za-z0-9_.-]+", stripped)
                if name:
                    declared_packages.add(name.group(0).lower())
    if has_pyproject:
        declared_packages.update(m.lower() for m in re.findall(r'"([A-Za-z0-9_.-]+)[><=!~\[]', files["pyproject.toml"]))

    # Checked against full relative paths (e.g. "app/main.py"), not just
    # basenames -- unlike the manifest files above, an entrypoint's location
    # in the tree is exactly what determines the module path uvicorn needs
    # (app.main:app vs main:app), so the basename alone isn't enough here.
    entrypoint_file, module_target, server = None, None, "python"
    for candidate_file, target, candidate_server in _PYTHON_ENTRYPOINT_CANDIDATES:
        if candidate_file in all_paths:
            entrypoint_file, module_target, server = candidate_file, target, candidate_server
            break

    is_fastapi = "fastapi" in declared_packages
    is_django = "django" in declared_packages or server == "django"
    is_flask = "flask" in declared_packages

    if is_fastapi and module_target:
        start_command = f"uvicorn {module_target} --host 0.0.0.0 --port 8000"
    elif is_django:
        start_command = "python manage.py runserver 0.0.0.0:8000"
    elif is_flask:
        start_command = "flask run --host=0.0.0.0 --port=8000"
    elif entrypoint_file:
        start_command = f"python {entrypoint_file}"
    else:
        start_command = "python -m app"  # honest best guess, no entrypoint file found

    return {
        "ecosystem": "python",
        "python_version": "3.12",
        "start_command": start_command,
        "install_command": "pip install -r requirements.txt" if has_requirements else "pip install .",
        "build_command": None,
        "port": 8000,
        "declared_packages": declared_packages,
    }


def _detected_services(stacks: list[dict]) -> list[str]:
    all_packages: set[str] = set()
    for stack in stacks:
        all_packages |= {p.lower() for p in stack["declared_packages"]}
    return [service for service, markers in _SERVICE_MARKER_PACKAGES.items() if all_packages & markers]


def _build_dockerfile(stacks: list[dict]) -> str:
    blocks: list[str] = []
    for stack in stacks:
        if stack["ecosystem"] == "node":
            blocks.append(
                f"# --- Node ---\n"
                f"FROM node:{stack['node_version']}-alpine AS node\n"
                f"WORKDIR /app\n"
                f"COPY package*.json ./\n"
                f"RUN {stack['install_command']}\n"
                f"COPY . .\n"
                + (f"RUN {stack['build_command']}\n" if stack["build_command"] else "")
                + f"EXPOSE {stack['port']}\n"
                f'CMD ["sh", "-c", "{stack["start_command"]}"]\n'
            )
        elif stack["ecosystem"] == "python":
            blocks.append(
                f"# --- Python ---\n"
                f"FROM python:{stack['python_version']}-slim AS python\n"
                f"WORKDIR /app\n"
                f"COPY requirements.txt* pyproject.toml* ./\n"
                f"RUN {stack['install_command']}\n"
                f"COPY . .\n"
                f"EXPOSE {stack['port']}\n"
                f'CMD ["sh", "-c", "{stack["start_command"]}"]\n'
            )
    # Two full FROM blocks in one file (rather than a true multi-stage
    # build) is intentional for a repo detected as both ecosystems -- e.g.
    # a Next.js frontend alongside a separate Python backend, this project's
    # own shape -- since the two apps are two independent services, not
    # stages of building one artifact; docker-compose.yml below is what
    # actually runs them side by side, each from its own `target`.
    return "\n".join(blocks)


def _build_compose(stacks: list[dict], services: list[str]) -> str:
    lines = ["services:"]
    for stack in stacks:
        name = stack["ecosystem"]
        lines.append(f"  {name}:")
        lines.append("    build:")
        lines.append("      context: .")
        lines.append(f"      target: {name}")
        lines.append(f'    ports: ["{stack["port"]}:{stack["port"]}"]')
        depends_on = services + [s["ecosystem"] for s in stacks if s is not stack and s["ecosystem"] != name]
        if depends_on:
            lines.append(f"    depends_on: [{', '.join(depends_on)}]")

    if "postgres" in services:
        lines += [
            "  postgres:",
            "    image: postgres:16-alpine",
            "    environment:",
            "      POSTGRES_PASSWORD: postgres",
            '    ports: ["5432:5432"]',
        ]
    if "redis" in services:
        lines += [
            "  redis:",
            "    image: redis:7-alpine",
            '    ports: ["6379:6379"]',
        ]
    return "\n".join(lines) + "\n"


def _build_setup_script(stacks: list[dict]) -> str:
    lines = ["#!/usr/bin/env bash", "set -euo pipefail", ""]
    for stack in stacks:
        lines.append(f"echo '--- Setting up {stack['ecosystem']} ---'")
        lines.append(stack["install_command"])
        if stack["build_command"]:
            lines.append(stack["build_command"])
        lines.append("")
    lines.append("echo 'Setup complete. Run: docker compose up --build'")
    return "\n".join(lines) + "\n"


def generate_bootstrap(files: list[File]) -> dict:
    """Fully deterministic -- always succeeds. `stacks_detected` is empty
    (and dockerfile/compose/setup_script are all empty strings) when neither
    a Node nor a Python manifest was found, rather than guessing."""
    by_basename: dict[str, str] = {}
    all_paths: set[str] = set()
    for f in files:
        normalized = f.path.replace("\\", "/")
        all_paths.add(normalized)
        name = normalized.rsplit("/", 1)[-1]
        if name in ("package.json", "package-lock.json", "requirements.txt", "pyproject.toml"):
            by_basename[name] = f.content

    stacks = [s for s in (_detect_node(by_basename), _detect_python(by_basename, all_paths)) if s is not None]
    services = _detected_services(stacks)

    if not stacks:
        return {
            "stacks_detected": [],
            "services_detected": [],
            "dockerfile": "",
            "docker_compose": "",
            "setup_script": "",
        }

    return {
        "stacks_detected": [s["ecosystem"] for s in stacks],
        "services_detected": services,
        "dockerfile": _build_dockerfile(stacks),
        "docker_compose": _build_compose(stacks, services),
        "setup_script": _build_setup_script(stacks),
    }
