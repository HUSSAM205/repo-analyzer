import pytest
from pydantic import ValidationError

from app.schemas.repos import RepoAnalyzeRequest


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/tiangolo/fastapi",
        "https://github.com/tiangolo/fastapi.git",
        "https://github.com/tiangolo/fastapi/",
        "https://GITHUB.COM/tiangolo/fastapi",
        "https://github.com/my.dotted-name_repo/another.repo-name_2",
    ],
)
def test_accepts_real_github_repo_urls(url):
    RepoAnalyzeRequest(repo_url=url)


@pytest.mark.parametrize(
    "url",
    [
        # Non-GitHub host -- the core SSRF vector: an internal host or cloud
        # metadata endpoint would otherwise be cloned exactly like a real
        # GitHub repo, from inside this service's network.
        "https://169.254.169.254/latest/meta-data/",
        "https://internal-service.local/repo",
        "https://gitlab.com/tiangolo/fastapi",
        "https://localhost/a/b",
        # Lookalike host -- github.com as a SUBDOMAIN of an attacker domain,
        # not the real github.com.
        "https://github.com.evil.com/a/b",
        "https://evil-github.com/a/b",
        # Non-https scheme -- also blocks git's own alternate-transport
        # helpers (ext::, ssh://, file://) that HttpUrl's scheme check alone
        # already rejects, but explicit is safer than implicit here.
        "http://github.com/a/b",
        # Embedded credentials.
        "https://user:pass@github.com/a/b",
        # Non-default port -- can't actually reach the real GitHub.
        "https://github.com:8080/a/b",
        # Malformed/missing repo path shape.
        "https://github.com/",
        "https://github.com/just-an-owner",
        "https://github.com/owner/repo/extra/segments",
    ],
)
def test_rejects_non_github_or_malformed_urls(url):
    with pytest.raises(ValidationError):
        RepoAnalyzeRequest(repo_url=url)
