from collections.abc import Awaitable, Callable
from typing import Annotated, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_repo_or_404
from app.core.compliance_scanner import run_compliance_scan
from app.core.doc_generator import build_deterministic_readme, generate_readme
from app.core.flow_map import build_deterministic_flow_map, generate_flow_map
from app.core.health_score import compute_health_score
from app.core.llm_providers import get_llm_client
from app.core.bootstrapper import generate_bootstrap
from app.core.complexity_radar import analyze_complexity
from app.core.module_map import build_module_map
from app.core.quiz_generator import build_deterministic_quiz, generate_quiz
from app.core.response_cache import get_cached, set_cached
from app.core.route_explorer import extract_routes
from app.core.security_scanner import build_deterministic_findings, scan_for_issues
from app.core.tech_debt import build_deterministic_tech_debt_report, generate_tech_debt_report
from app.db.models import File, Repo, RepoStatus, User
from app.db.session import get_db
from app.schemas.flagship import (
    BootstrapResponse,
    ComplexityRadarResponse,
    ComplianceScanResponse,
    FlowMapResponse,
    HealthScoreResponse,
    ModuleMapResponse,
    QuizResponse,
    ReadmeResponse,
    RouteExplorerResponse,
    SecurityScanResponse,
    TechDebtResponse,
)

router = APIRouter(prefix="/api/v1/repos", tags=["flagship"])

_NOT_READY_DETAIL = "This repository hasn't finished analyzing yet."
_UNAVAILABLE_DETAIL = "The AI provider is temporarily unavailable. Please try again."

_ModelT = TypeVar("_ModelT", bound=BaseModel)


async def _load_files_or_409(db: AsyncSession, repo: Repo) -> list[File]:
    if repo.status != RepoStatus.READY:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_NOT_READY_DETAIL)
    result = await db.execute(select(File).where(File.repo_id == repo.id))
    return list(result.scalars().all())


async def _cached_or_compute(
    cache_key: str, model_cls: type[_ModelT], compute: Callable[[], Awaitable[_ModelT]]
) -> _ModelT:
    """Redis read-through wrapper around one flagship tool's existing
    lazy-generate-and-cache logic (`compute`) -- see response_cache.py for
    why this sits in front of, not instead of, each tool's permanent
    Postgres cache. `compute` still does its own Postgres cache check/write
    exactly as before; this only adds a faster, TTL'd layer in front of it.
    A 409 (not ready) or 503 (generation failed) raised by `compute` simply
    propagates -- never cached, same as the Postgres layer's own contract.
    """
    cached = await get_cached(cache_key)
    if cached is not None:
        return model_cls.model_validate_json(cached)

    result = await compute()
    await set_cached(cache_key, result.model_dump_json())
    return result


# Every route below follows the exact same lazy-generate-and-cache contract
# as files.py's get_file_annotations: cached on the Repo row (permanently)
# and fronted by Redis (24h TTL, see response_cache.py) so a repeat/
# concurrent request for the same repo never re-invokes the LLM or even
# touches Postgres. A generation failure (LLM error/timeout/empty response)
# is surfaced as 503 and never cached at either layer, so a later request
# can retry once the provider recovers.


@router.get("/{repo_id}/readme", response_model=ReadmeResponse)
async def get_readme(
    repo_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReadmeResponse:
    repo = await get_repo_or_404(db, repo_id, current_user)

    async def _compute() -> ReadmeResponse:
        if repo.readme_doc is not None:
            return ReadmeResponse(content=repo.readme_doc)
        files = await _load_files_or_409(db, repo)
        # A deterministic fallback (see doc_generator.py) stands in for the
        # AI-written draft when the LLM provider is unavailable -- a viewer
        # always gets a real document, never a 503.
        content = await generate_readme(files, repo.domain_briefing, get_llm_client()) or build_deterministic_readme(
            files, repo.domain_briefing
        )
        repo.readme_doc = content
        await db.commit()
        return ReadmeResponse(content=content)

    return await _cached_or_compute(f"flagship:readme:{repo_id}", ReadmeResponse, _compute)


@router.get("/{repo_id}/security-scan", response_model=SecurityScanResponse)
async def get_security_scan(
    repo_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SecurityScanResponse:
    repo = await get_repo_or_404(db, repo_id, current_user)

    async def _compute() -> SecurityScanResponse:
        if repo.security_scan is not None:
            return SecurityScanResponse(findings=repo.security_scan)
        files = await _load_files_or_409(db, repo)
        findings = await scan_for_issues(files, get_llm_client())
        if findings is None:
            # Deterministic fallback (see security_scanner.py) -- distinct
            # from an empty list, which is itself a valid "no issues found"
            # result from the real scan and must not be replaced.
            findings = build_deterministic_findings(files)
        repo.security_scan = findings
        await db.commit()
        return SecurityScanResponse(findings=findings)

    return await _cached_or_compute(f"flagship:security-scan:{repo_id}", SecurityScanResponse, _compute)


@router.get("/{repo_id}/health-score", response_model=HealthScoreResponse)
async def get_health_score(
    repo_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HealthScoreResponse:
    repo = await get_repo_or_404(db, repo_id, current_user)

    async def _compute() -> HealthScoreResponse:
        if repo.health_score is not None:
            return HealthScoreResponse.model_validate(repo.health_score)
        files = await _load_files_or_409(db, repo)
        score = await compute_health_score(files, get_llm_client())
        if score is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_UNAVAILABLE_DETAIL)
        repo.health_score = score
        await db.commit()
        return HealthScoreResponse.model_validate(score)

    return await _cached_or_compute(f"flagship:health-score:{repo_id}", HealthScoreResponse, _compute)


@router.get("/{repo_id}/quiz", response_model=QuizResponse)
async def get_quiz(
    repo_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QuizResponse:
    repo = await get_repo_or_404(db, repo_id, current_user)

    async def _compute() -> QuizResponse:
        if repo.quiz is not None:
            return QuizResponse(questions=repo.quiz)
        files = await _load_files_or_409(db, repo)
        # A deterministic, file-tree-fact quiz (see quiz_generator.py) stands
        # in for the AI-written comprehension quiz when the LLM provider is
        # unavailable -- a viewer always gets a real quiz, never a 503.
        questions = await generate_quiz(files, get_llm_client()) or build_deterministic_quiz(files)
        if questions is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_UNAVAILABLE_DETAIL)
        repo.quiz = questions
        await db.commit()
        return QuizResponse(questions=questions)

    return await _cached_or_compute(f"flagship:quiz:{repo_id}", QuizResponse, _compute)


@router.get("/{repo_id}/flow-map", response_model=FlowMapResponse)
async def get_flow_map(
    repo_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FlowMapResponse:
    repo = await get_repo_or_404(db, repo_id, current_user)

    async def _compute() -> FlowMapResponse:
        if repo.flow_map is not None:
            return FlowMapResponse(diagram=repo.flow_map)
        files = await _load_files_or_409(db, repo)
        # A deterministic, heuristic-only diagram (see flow_map.py) stands
        # in for the AI-generated one when the LLM provider is unavailable
        # -- a viewer always gets a real, valid diagram, never a 503.
        diagram = await generate_flow_map(files, get_llm_client()) or build_deterministic_flow_map(files)
        repo.flow_map = diagram
        await db.commit()
        return FlowMapResponse(diagram=diagram)

    return await _cached_or_compute(f"flagship:flow-map:{repo_id}", FlowMapResponse, _compute)


@router.get("/{repo_id}/tech-debt", response_model=TechDebtResponse)
async def get_tech_debt(
    repo_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TechDebtResponse:
    repo = await get_repo_or_404(db, repo_id, current_user)

    async def _compute() -> TechDebtResponse:
        if repo.tech_debt is not None:
            return TechDebtResponse.model_validate(repo.tech_debt)
        files = await _load_files_or_409(db, repo)
        # A deterministic, heuristic-only report (see tech_debt.py) stands
        # in for the AI-generated one when the LLM provider is unavailable
        # -- a viewer always gets a real report, never a 503.
        report = await generate_tech_debt_report(files, get_llm_client()) or build_deterministic_tech_debt_report(files)
        repo.tech_debt = report
        await db.commit()
        return TechDebtResponse.model_validate(report)

    return await _cached_or_compute(f"flagship:tech-debt:{repo_id}", TechDebtResponse, _compute)


@router.get("/{repo_id}/compliance-scan", response_model=ComplianceScanResponse)
async def get_compliance_scan(
    repo_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ComplianceScanResponse:
    repo = await get_repo_or_404(db, repo_id, current_user)

    async def _compute() -> ComplianceScanResponse:
        if repo.compliance_scan is not None:
            return ComplianceScanResponse.model_validate(repo.compliance_scan)
        files = await _load_files_or_409(db, repo)
        # Fully deterministic (no LLM call) -- see compliance_scanner.py --
        # so there is no failure case to handle here, unlike every other
        # route in this file.
        scan = run_compliance_scan(files)
        repo.compliance_scan = scan
        await db.commit()
        return ComplianceScanResponse.model_validate(scan)

    return await _cached_or_compute(f"flagship:compliance-scan:{repo_id}", ComplianceScanResponse, _compute)


@router.get("/{repo_id}/routes", response_model=RouteExplorerResponse)
async def get_routes(
    repo_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RouteExplorerResponse:
    repo = await get_repo_or_404(db, repo_id, current_user)

    async def _compute() -> RouteExplorerResponse:
        # Fully deterministic (no LLM call, see route_explorer.py) and cheap
        # to recompute (a regex scan over already-loaded files) -- unlike
        # every other tool in this file, this one deliberately has no
        # permanent Postgres cache column, only the Redis TTL layer below.
        # Skips a schema migration entirely for a result that's fast enough
        # to just regenerate on a cache miss.
        files = await _load_files_or_409(db, repo)
        return RouteExplorerResponse.model_validate(extract_routes(files))

    return await _cached_or_compute(f"flagship:routes:{repo_id}", RouteExplorerResponse, _compute)


@router.get("/{repo_id}/module-map", response_model=ModuleMapResponse)
async def get_module_map(
    repo_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ModuleMapResponse:
    repo = await get_repo_or_404(db, repo_id, current_user)

    async def _compute() -> ModuleMapResponse:
        # Fully deterministic (see module_map.py) and cheap -- no permanent
        # Postgres cache column, same reasoning as get_routes above.
        files = await _load_files_or_409(db, repo)
        return ModuleMapResponse.model_validate(build_module_map(files))

    return await _cached_or_compute(f"flagship:module-map:{repo_id}", ModuleMapResponse, _compute)


@router.get("/{repo_id}/bootstrap", response_model=BootstrapResponse)
async def get_bootstrap(
    repo_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BootstrapResponse:
    repo = await get_repo_or_404(db, repo_id, current_user)

    async def _compute() -> BootstrapResponse:
        # Fully deterministic (see bootstrapper.py) and cheap -- no
        # permanent Postgres cache column, same reasoning as get_routes.
        files = await _load_files_or_409(db, repo)
        return BootstrapResponse.model_validate(generate_bootstrap(files))

    return await _cached_or_compute(f"flagship:bootstrap:{repo_id}", BootstrapResponse, _compute)


@router.get("/{repo_id}/complexity", response_model=ComplexityRadarResponse)
async def get_complexity_radar(
    repo_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ComplexityRadarResponse:
    repo = await get_repo_or_404(db, repo_id, current_user)

    async def _compute() -> ComplexityRadarResponse:
        # Fully deterministic (see complexity_radar.py) -- no permanent
        # Postgres cache column, same reasoning as get_routes/get_module_map,
        # though this one is the most expensive of the three to recompute
        # (a real tree-sitter parse per file) so the Redis layer matters
        # more here than for the others.
        files = await _load_files_or_409(db, repo)
        return ComplexityRadarResponse.model_validate(analyze_complexity(files))

    return await _cached_or_compute(f"flagship:complexity:{repo_id}", ComplexityRadarResponse, _compute)
