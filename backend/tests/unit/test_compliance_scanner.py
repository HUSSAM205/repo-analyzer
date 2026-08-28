import json
import uuid

from app.core.compliance_scanner import run_compliance_scan
from app.db.models import File


def _file(path: str, content: str = "content") -> File:
    return File(id=uuid.uuid4(), repo_id=uuid.uuid4(), path=path, content=content)


def test_detects_aws_access_key():
    files = [_file("config.py", 'AWS_KEY = "AKIAABCDEFGHIJKLMNOP"')]
    result = run_compliance_scan(files)
    assert len(result["secret_findings"]) == 1
    assert result["secret_findings"][0]["pattern"] == "AWS Access Key ID"
    assert "AKIA" not in result["secret_findings"][0]["preview"] or result["secret_findings"][0]["preview"] != "AKIAABCDEFGHIJKLMNOP"
    assert result["overall_risk"] == "high"


def test_detects_private_key_block():
    files = [_file("id_rsa", "-----BEGIN RSA PRIVATE KEY-----\nMIIExxxx\n-----END RSA PRIVATE KEY-----")]
    result = run_compliance_scan(files)
    assert any(f["pattern"] == "Private key block" for f in result["secret_findings"])


def test_ignores_placeholder_values():
    files = [_file(".env.example", 'API_KEY="changeme"\npassword = "placeholder"')]
    result = run_compliance_scan(files)
    assert result["secret_findings"] == []


def test_redacts_the_secret_value_in_the_preview():
    files = [_file("settings.py", 'password = "supersecretvalue123"')]
    result = run_compliance_scan(files)
    assert len(result["secret_findings"]) == 1
    preview = result["secret_findings"][0]["preview"]
    assert "supersecretvalue123" not in preview
    assert "*" in preview


def test_classifies_known_npm_packages_as_low_risk():
    package_json = json.dumps({"dependencies": {"react": "18.3.1", "express": "4.19.2"}})
    files = [_file("package.json", package_json)]
    result = run_compliance_scan(files)
    packages = {f["package"]: f for f in result["license_findings"]}
    assert packages["react"]["likely_license"] == "MIT"
    assert packages["react"]["risk"] == "low"
    assert result["overall_risk"] == "low"


def test_unknown_package_is_flagged_unknown_not_guessed():
    package_json = json.dumps({"dependencies": {"some-obscure-internal-lib": "1.0.0"}})
    files = [_file("package.json", package_json)]
    result = run_compliance_scan(files)
    [finding] = result["license_findings"]
    assert finding["likely_license"] == "Unknown"
    assert finding["risk"] == "unknown"


def test_gpl_dependency_raises_overall_risk_to_high():
    requirements = "PyQt5==5.15.0\nrequests==2.31.0"
    files = [_file("requirements.txt", requirements)]
    result = run_compliance_scan(files)
    risks = {f["package"]: f["risk"] for f in result["license_findings"]}
    assert risks["PyQt5"] == "high"
    assert result["overall_risk"] == "high"


def test_clean_repo_has_low_risk_and_empty_findings():
    files = [_file("main.py", "def main():\n    print('hello')\n")]
    result = run_compliance_scan(files)
    assert result["overall_risk"] == "low"
    assert result["secret_findings"] == []
    assert result["license_findings"] == []
    assert result["dangerous_pattern_findings"] == []


def test_detects_python_eval_but_not_ast_literal_eval():
    files = [_file("app.py", "result = eval(user_input)\nsafe = ast.literal_eval(user_input)\n")]
    result = run_compliance_scan(files)
    findings = result["dangerous_pattern_findings"]
    assert len(findings) == 1
    assert findings[0]["pattern"] == "eval()"
    assert findings[0]["line"] == 1
    assert findings[0]["severity"] == "high"
    assert result["overall_risk"] == "high"


def test_detects_subprocess_shell_true():
    files = [_file("deploy.py", "subprocess.run(cmd, shell=True)")]
    result = run_compliance_scan(files)
    [finding] = result["dangerous_pattern_findings"]
    assert finding["pattern"] == "subprocess shell=True"
    assert finding["severity"] == "high"


def test_detects_pickle_deserialization():
    files = [_file("cache.py", "data = pickle.loads(raw_bytes)")]
    result = run_compliance_scan(files)
    assert any(f["pattern"] == "pickle deserialization" for f in result["dangerous_pattern_findings"])


def test_detects_unsafe_yaml_load_but_not_safe_load():
    files = [_file(
        "config.py",
        "unsafe = yaml.load(stream)\nsafe = yaml.load(stream, Loader=yaml.SafeLoader)\nalso_safe = yaml.safe_load(stream)\n",
    )]
    result = run_compliance_scan(files)
    findings = [f for f in result["dangerous_pattern_findings"] if f["pattern"] == "yaml.load() without a safe loader"]
    assert len(findings) == 1
    assert findings[0]["line"] == 1


def test_detects_react_dangerously_set_inner_html_and_raw_inner_html_assignment():
    files = [_file(
        "Widget.tsx",
        '<div dangerouslySetInnerHTML={{ __html: raw }} />\nel.innerHTML = userContent;\nconst same = a === b;\n',
    )]
    result = run_compliance_scan(files)
    patterns = {f["pattern"] for f in result["dangerous_pattern_findings"]}
    assert "dangerouslySetInnerHTML" in patterns
    assert "innerHTML assignment" in patterns
    # `===` must not be mistaken for an innerHTML-style assignment.
    assert not any("a === b" in f["snippet"] for f in result["dangerous_pattern_findings"])
    assert result["overall_risk"] == "medium"


def test_dangerous_pattern_scan_skips_non_code_files():
    files = [_file("README.md", "Run eval(1+1) in your REPL to try it out.")]
    result = run_compliance_scan(files)
    assert result["dangerous_pattern_findings"] == []


def test_dangerous_pattern_snippet_is_truncated_and_trimmed():
    long_line = "    " + "eval(" + "x" * 300 + ")"
    files = [_file("app.py", long_line)]
    result = run_compliance_scan(files)
    [finding] = result["dangerous_pattern_findings"]
    assert not finding["snippet"].startswith(" ")
    assert len(finding["snippet"]) <= 200


def test_extracts_requirements_txt_packages_with_version_pins():
    files = [_file("requirements.txt", "flask==2.3.0\n# a comment\nnumpy>=1.20\n\ndjango")]
    result = run_compliance_scan(files)
    packages = {f["package"] for f in result["license_findings"]}
    assert packages == {"flask", "numpy", "django"}


def test_extracts_pep_621_style_pyproject_dependencies_array():
    # PEP 621 (what FastAPI's own pyproject.toml uses, among many others)
    # declares dependencies as a plain array of requirement strings under
    # [project] -- a different shape from Poetry's `name = "version"` table
    # entries, and confirmed live to previously fall through to "no
    # manifest found" for a real repo using this format.
    pyproject = (
        "[project]\n"
        'name = "myapp"\n'
        "dependencies = [\n"
        '    "starlette>=0.40.0,<0.41.0",\n'
        '    "pydantic>=1.7.4,!=1.8,!=1.8.1,<3.0.0",\n'
        '    "fastapi[all]",\n'
        "]\n"
    )
    files = [_file("pyproject.toml", pyproject)]
    result = run_compliance_scan(files)
    packages = {f["package"] for f in result["license_findings"]}
    assert packages == {"starlette", "pydantic", "fastapi"}


def test_never_raises_on_malformed_package_json():
    files = [_file("package.json", "{not valid json")]
    result = run_compliance_scan(files)
    assert result["license_findings"] == []
