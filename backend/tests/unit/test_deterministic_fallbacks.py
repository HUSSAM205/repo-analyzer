import uuid

from app.core.doc_generator import build_deterministic_readme
from app.core.flow_map import build_deterministic_flow_map
from app.core.quiz_generator import build_deterministic_quiz
from app.core.security_scanner import build_deterministic_findings
from app.core.tech_debt import build_deterministic_tech_debt_report
from app.db.models import File


def _file(path: str, content: str = "content") -> File:
    return File(id=uuid.uuid4(), repo_id=uuid.uuid4(), path=path, content=content)


class TestDeterministicFlowMap:
    def test_produces_a_valid_diagram_for_a_repo_with_no_recognizable_layers(self):
        diagram = build_deterministic_flow_map([_file("README.md"), _file("main.py")])
        assert diagram.startswith("flowchart TD")
        assert "Client" in diagram
        assert "-->" in diagram

    def test_detects_layered_architecture_from_directory_names(self):
        files = [
            _file("app/routes/users.py"),
            _file("app/services/user_service.py"),
            _file("app/models/user.py"),
        ]
        diagram = build_deterministic_flow_map(files)
        assert "Routes / Controllers" in diagram
        assert "Services / Business Logic" in diagram
        assert "Models / Data Layer" in diagram
        assert "Database" in diagram

    def test_never_raises_on_an_empty_file_list(self):
        diagram = build_deterministic_flow_map([])
        assert diagram.startswith("flowchart TD")


class TestDeterministicTechDebt:
    def test_flags_missing_tests_and_ci(self):
        report = build_deterministic_tech_debt_report([_file("main.py", "print('hi')\n")])
        issues = {item["issue"] for item in report["items"]}
        assert any("No test files detected" in i for i in issues)
        assert any("No CI configuration detected" in i for i in issues)
        assert report["estimated_debt_hours"] == 10.0

    def test_does_not_flag_tests_or_ci_when_present(self):
        files = [
            _file("main.py", "print('hi')\n"),
            _file("tests/test_main.py", "def test_x(): pass\n"),
            _file(".github/workflows/ci.yml", "name: CI\n"),
        ]
        report = build_deterministic_tech_debt_report(files)
        issues = {item["issue"] for item in report["items"]}
        assert not any("No test files detected" in i for i in issues)
        assert not any("No CI configuration detected" in i for i in issues)

    def test_flags_large_files_by_line_count(self):
        large_content = "\n".join(f"line {i}" for i in range(500))
        files = [
            _file("big.py", large_content),
            _file("tests/test_x.py", "def test_x(): pass\n"),
            _file(".github/workflows/ci.yml", "name: CI\n"),
        ]
        report = build_deterministic_tech_debt_report(files)
        assert len(report["items"]) == 1
        assert "big.py" in report["items"][0]["file"]
        assert "500 lines" in report["items"][0]["issue"]

    def test_summary_is_honest_about_being_a_fallback(self):
        report = build_deterministic_tech_debt_report([_file("main.py")])
        assert "temporarily unavailable" in report["summary"]

    def test_never_raises_on_an_empty_file_list(self):
        report = build_deterministic_tech_debt_report([])
        assert report["items"]  # still flags missing tests/CI
        assert isinstance(report["estimated_debt_hours"], float)


class TestDeterministicReadme:
    def test_returns_existing_readme_verbatim_when_present(self):
        readme_body = "# My Real Project\n\nThis is the actual, human-written README."
        files = [_file("README.md", readme_body), _file("main.py")]
        result = build_deterministic_readme(files, domain_briefing=None)
        assert readme_body in result
        assert "temporarily unavailable" in result

    def test_builds_a_minimal_readme_from_domain_briefing_when_none_exists(self):
        briefing = {
            "primary_field": "Web SaaS",
            "target_audience": "Backend engineers",
            "architecture_overview": "A FastAPI backend talks to Postgres.",
            "tech_stack_badges": ["Python", "FastAPI"],
        }
        files = [_file("main.py"), _file("app/routes.py")]
        result = build_deterministic_readme(files, briefing)
        assert "Web SaaS" in result
        assert "Backend engineers" in result
        assert "A FastAPI backend talks to Postgres." in result
        assert "Python, FastAPI" in result
        assert "main.py" in result

    def test_never_raises_with_no_readme_and_no_briefing(self):
        result = build_deterministic_readme([_file("main.py")], domain_briefing=None)
        assert "main.py" in result
        assert "temporarily unavailable" in result


class TestDeterministicSecurityFindings:
    def test_flags_detected_secrets_as_high_severity_security_findings(self):
        files = [_file("config.py", 'AWS_KEY = "AKIAABCDEFGHIJKLMNOP"')]
        findings = build_deterministic_findings(files)
        assert len(findings) == 1
        assert findings[0]["severity"] == "high"
        assert findings[0]["category"] == "security"
        assert findings[0]["file"] == "config.py"

    def test_empty_list_for_a_clean_repo_is_a_valid_result(self):
        findings = build_deterministic_findings([_file("main.py", "def main():\n    pass\n")])
        assert findings == []


class TestDeterministicQuiz:
    def test_produces_exactly_three_questions_with_four_options_each(self):
        files = [
            _file("app/main.py", "print('hi')"),
            _file("app/utils.py", "def helper(): pass"),
            _file("tests/test_main.py", "def test_x(): pass"),
        ]
        questions = build_deterministic_quiz(files)
        assert questions is not None
        assert len(questions) == 3
        for q in questions:
            assert len(q["options"]) == 4
            assert 0 <= q["correct_index"] < 4
            assert q["options"][q["correct_index"]]  # correct answer is a real string

    def test_correctly_identifies_the_primary_language(self):
        files = [_file(f"module_{i}.py", "x = 1") for i in range(5)] + [_file("script.sh", "echo hi")]
        questions = build_deterministic_quiz(files)
        lang_question = questions[0]
        correct_answer = lang_question["options"][lang_question["correct_index"]]
        assert correct_answer == "Python"

    def test_correctly_identifies_presence_of_tests(self):
        files = [_file("main.py"), _file("tests/test_main.py")]
        questions = build_deterministic_quiz(files)
        test_question = questions[2]
        correct_answer = test_question["options"][test_question["correct_index"]]
        assert "Yes" in correct_answer

    def test_correctly_identifies_absence_of_tests(self):
        files = [_file("main.py")]
        questions = build_deterministic_quiz(files)
        test_question = questions[2]
        correct_answer = test_question["options"][test_question["correct_index"]]
        assert "No" in correct_answer

    def test_returns_none_for_an_empty_repo(self):
        assert build_deterministic_quiz([]) is None
