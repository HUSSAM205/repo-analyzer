from pydantic import BaseModel


class ReadmeResponse(BaseModel):
    content: str


class SecurityFinding(BaseModel):
    severity: str
    category: str
    file: str
    line: int | None
    title: str
    description: str


class SecurityScanResponse(BaseModel):
    findings: list[SecurityFinding]


class HealthSubScores(BaseModel):
    documentation: int
    testing: int
    automation: int
    quality: int


class HealthSignals(BaseModel):
    has_readme: bool
    has_tests: bool
    has_ci: bool
    has_license: bool


class HealthScoreResponse(BaseModel):
    overall_score: int
    sub_scores: HealthSubScores
    commentary: str
    signals: HealthSignals


class QuizQuestion(BaseModel):
    question: str
    options: list[str]
    correct_index: int
    explanation: str


class QuizResponse(BaseModel):
    questions: list[QuizQuestion]


class FlowMapResponse(BaseModel):
    diagram: str


class RefactorRecipe(BaseModel):
    file: str
    issue: str
    estimated_hours: float
    before_snippet: str
    after_snippet: str
    explanation: str


class TechDebtResponse(BaseModel):
    estimated_debt_hours: float
    summary: str
    items: list[RefactorRecipe]


class LicenseFinding(BaseModel):
    package: str
    ecosystem: str
    likely_license: str
    risk: str
    note: str


class SecretFinding(BaseModel):
    file: str
    line: int
    pattern: str
    preview: str


class DangerousPatternFinding(BaseModel):
    file: str
    line: int
    pattern: str
    severity: str
    rationale: str
    snippet: str


class ComplexityHotspot(BaseModel):
    file: str
    function: str
    line: int
    complexity: int
    maintainability: int
    line_count: int


class ComplexityRadarResponse(BaseModel):
    functions_analyzed: int
    average_complexity: float
    hotspots: list[ComplexityHotspot]
    disclaimer: str


class BootstrapResponse(BaseModel):
    stacks_detected: list[str]
    services_detected: list[str]
    dockerfile: str
    docker_compose: str
    setup_script: str


class ModuleMapResponse(BaseModel):
    diagram: str
    directory_count: int
    file_count: int


class RouteFinding(BaseModel):
    method: str
    path: str
    file: str
    line: int
    framework: str
    path_params: list[str]
    auth_required: bool


class RouteExplorerResponse(BaseModel):
    routes: list[RouteFinding]
    frameworks_detected: list[str]
    disclaimer: str


class ComplianceScanResponse(BaseModel):
    overall_risk: str
    license_findings: list[LicenseFinding]
    secret_findings: list[SecretFinding]
    # Defaulted, not required -- a repo whose compliance_scan was cached
    # before this field existed (see flagship.py's get_compliance_scan)
    # still has an old-shaped dict with no such key, and that cache is
    # permanent (never recomputed for an already-analyzed repo). Without a
    # default, validating that old dict against this schema would 500
    # instead of just showing a stale scan missing the new section.
    dangerous_pattern_findings: list[DangerousPatternFinding] = []
    disclaimer: str


class RepoMetrics(BaseModel):
    file_count: int
    lines_of_code: int
    average_complexity: float
    functions_analyzed: int
    route_count: int
    frameworks_detected: list[str]
    vulnerability_count: int
    overall_risk: str
    module_breakdown: dict[str, int]


class RepoCompareSide(BaseModel):
    repo_id: str
    name: str
    url: str
    metrics: RepoMetrics


class RepoCompareDeltas(BaseModel):
    file_count_delta: int
    lines_of_code_delta: int
    average_complexity_delta: float
    route_count_delta: int
    vulnerability_count_delta: int


class RepoCompareResponse(BaseModel):
    repo_a: RepoCompareSide
    repo_b: RepoCompareSide
    deltas: RepoCompareDeltas
    security_verdict: str
    disclaimer: str
