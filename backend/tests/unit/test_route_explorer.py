import uuid

from app.core.route_explorer import extract_routes
from app.db.models import File


def _file(path: str, content: str) -> File:
    return File(id=uuid.uuid4(), repo_id=uuid.uuid4(), path=path, content=content)


def test_extracts_fastapi_route_with_router_prefix_and_path_param():
    content = (
        'router = APIRouter(prefix="/api/v1/repos", tags=["repos"])\n\n'
        '@router.get("/{repo_id}")\n'
        "async def get_repo(repo_id: UUID):\n"
        "    ...\n"
    )
    result = extract_routes([_file("app/api/routes/repos.py", content)])
    [route] = result["routes"]
    assert route["method"] == "GET"
    assert route["path"] == "/api/v1/repos/{repo_id}"
    assert route["path_params"] == ["repo_id"]
    assert route["framework"] == "fastapi"
    assert "fastapi" in result["frameworks_detected"]


def test_extracts_fastapi_route_with_no_router_prefix():
    content = '@app.get("/health")\nasync def health():\n    return {"status": "ok"}\n'
    result = extract_routes([_file("app/main.py", content)])
    [route] = result["routes"]
    assert route["path"] == "/health"


def test_flags_fastapi_route_as_auth_required_when_depends_get_current_user_is_nearby():
    content = (
        '@router.delete("/{repo_id}")\n'
        "async def delete_repo(\n"
        "    repo_id: UUID,\n"
        "    current_user: Annotated[User, Depends(get_current_user)],\n"
        "):\n"
        "    ...\n"
    )
    result = extract_routes([_file("app/api/routes/repos.py", content)])
    [route] = result["routes"]
    assert route["auth_required"] is True


def test_does_not_flag_fastapi_route_as_auth_required_with_no_auth_dependency():
    content = '@router.get("/health")\nasync def health():\n    return {"status": "ok"}\n'
    result = extract_routes([_file("app/main.py", content)])
    [route] = result["routes"]
    assert route["auth_required"] is False


def test_extracts_express_route_with_path_param():
    content = "router.post('/users/:userId/orders', authMiddleware, (req, res) => {\n  res.json({});\n});\n"
    result = extract_routes([_file("src/routes/orders.js", content)])
    [route] = result["routes"]
    assert route["method"] == "POST"
    assert route["path"] == "/users/:userId/orders"
    assert route["path_params"] == ["userId"]
    assert route["framework"] == "express"
    assert route["auth_required"] is True


def test_extracts_nextjs_app_router_route_with_dynamic_segment():
    content = (
        "export async function GET(request, { params }) {\n"
        "  return Response.json({ id: params.repoId });\n"
        "}\n\n"
        "export async function POST(request) {\n"
        "  return Response.json({});\n"
        "}\n"
    )
    result = extract_routes([_file("app/api/repos/[repoId]/route.ts", content)])
    methods = {r["method"] for r in result["routes"]}
    assert methods == {"GET", "POST"}
    assert all(r["path"] == "/api/repos/{repoId}" for r in result["routes"])
    assert all(r["framework"] == "nextjs" for r in result["routes"])


def test_nextjs_route_group_segments_are_dropped_from_the_url():
    content = "export async function GET() {\n  return Response.json({});\n}\n"
    result = extract_routes([_file("app/(dashboard)/api/stats/route.ts", content)])
    [route] = result["routes"]
    assert route["path"] == "/api/stats"


def test_ignores_a_route_ts_file_outside_the_app_directory():
    content = "export async function GET() { return null; }\n"
    result = extract_routes([_file("scripts/route.ts", content)])
    assert result["routes"] == []


def test_clean_repo_has_no_routes():
    result = extract_routes([_file("README.md", "# hello")])
    assert result["routes"] == []
    assert result["frameworks_detected"] == []


def test_frameworks_detected_lists_each_framework_found_once():
    files = [
        _file("app/main.py", '@app.get("/health")\nasync def health(): ...\n'),
        _file("src/index.js", "app.get('/ping', (req, res) => res.send('pong'));\n"),
    ]
    result = extract_routes(files)
    assert result["frameworks_detected"] == ["express", "fastapi"]
