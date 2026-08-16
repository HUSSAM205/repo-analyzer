# Foundation + Analysis Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working backend (FastAPI + Postgres/pgvector + Redis/ARQ) that can accept a GitHub repo URL, clone it, parse it with Tree-sitter, chunk it at function/class granularity, embed chunks locally with CodeBERT, and answer hybrid (vector + keyword) search queries against it — proven end-to-end via automated tests and a docker-compose smoke test, no frontend.

**Architecture:** Async job-queue architecture. `POST /repos/analyze` enqueues an ARQ (Redis-backed) background job and returns immediately with a job id; a separate worker process clones/parses/chunks/embeds/stores and updates job progress; `GET /jobs/{id}` polls status; `POST /search` runs pgvector cosine search + Postgres full-text search and fuses results with reciprocal rank fusion.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2.0 (async, asyncpg), Alembic, PostgreSQL + pgvector, Redis, ARQ, Tree-sitter (via `tree-sitter-languages`), Hugging Face Transformers + PyTorch (CPU) for `microsoft/codebert-base` embeddings, GitPython, PyJWT (RS256), passlib/bcrypt, pytest + pytest-asyncio + httpx.

**Spec:** `docs/superpowers/specs/2026-08-16-analysis-core-design.md`

## Global Constraints

- Backend only in this plan — no frontend (Next.js UI is a later sub-project)
- Async job-queue architecture (Redis + ARQ) — no synchronous in-request repo processing
- Tree-sitter language support at launch: Python, JavaScript/TypeScript(+TSX), Go, Java, via an extensible parser registry; unsupported languages fall back to sliding-window text chunking, never a hard failure
- Embedding model: `microsoft/codebert-base` via HF Transformers, CPU/torch, no GPU required
- Auth: JWT RS256 + hashed API keys, single-tenant-per-user workspace model
- Rate limiting: Redis token bucket on `POST /repos/analyze`
- DB: PostgreSQL + pgvector extension; SQLAlchemy 2.0 async + asyncpg; Alembic migrations
- No Playwright/frontend tests in this plan
- No live GitHub network calls in integration tests — use a local fixture repo
- No placeholders — every file created is real, runnable code

---

## Prerequisites (once, before Task 1)

- Docker Desktop must be running (`docker ps` should succeed) before any task that depends on Postgres/Redis (Tasks 2 onward for integration tests).
- Python 3.12 and a virtual environment for `backend/`.

- [ ] **Step 1: Create the backend virtual environment**

```bash
cd C:/Users/hossa/Downloads/repo-analyzer
mkdir backend
cd backend
python -m venv .venv
```

- [ ] **Step 2: Activate it (Windows Git Bash)**

```bash
source .venv/Scripts/activate
```

---

### Task 1: Project scaffold, config, and health check endpoint

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/main.py`
- Create: `backend/.env.example`
- Create: `backend/pytest.ini`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/unit/__init__.py`
- Test: `backend/tests/unit/test_health.py`
- Create: `.gitignore` (root)

**Interfaces:**
- Produces: `app.config.Settings` (pydantic-settings), `app.config.get_settings()` cached accessor with fields: `database_url`, `redis_url`, `jwt_private_key_path`, `jwt_public_key_path`, `jwt_algorithm`, `jwt_access_token_expire_minutes`, `embedding_model_name`, `embedding_dimension`, `max_repo_size_mb`, `max_files_per_repo`, `clone_timeout_seconds`, `rate_limit_analyze_per_minute`, `rate_limit_bucket_capacity`
- Produces: `app.main.app` (FastAPI instance) with `GET /health`

- [ ] **Step 1: Write requirements.txt**

```
fastapi==0.115.0
uvicorn[standard]==0.32.0
pydantic==2.9.2
pydantic-settings==2.6.0
email-validator==2.2.0
sqlalchemy[asyncio]==2.0.36
asyncpg==0.30.0
alembic==1.13.3
pgvector==0.3.6
arq==0.26.1
redis==5.1.1
passlib[bcrypt]==1.7.4
pyjwt==2.9.0
cryptography==43.0.3
tree-sitter==0.23.1
tree-sitter-languages==1.10.2
transformers==4.46.0
torch==2.5.1
gitpython==3.1.43
httpx==0.27.2
pytest==8.3.3
pytest-asyncio==0.24.0
pytest-cov==5.0.0
python-dotenv==1.0.1
```

Install: `pip install -r requirements.txt` (this takes a while — torch and transformers are large downloads).

- [ ] **Step 2: Write the failing test**

`backend/tests/unit/test_health.py`:
```python
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

Also create empty `backend/tests/__init__.py` and `backend/tests/unit/__init__.py`.

- [ ] **Step 3: Run it, verify it fails**

Run: `pytest tests/unit/test_health.py -v` (from `backend/`)
Expected: FAIL with `ModuleNotFoundError: No module named 'app'` or similar.

- [ ] **Step 4: Write app/config.py**

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://repoanalyzer:repoanalyzer@localhost:5432/repoanalyzer"
    redis_url: str = "redis://localhost:6379/0"

    jwt_private_key_path: str = "keys/jwt_private.pem"
    jwt_public_key_path: str = "keys/jwt_public.pem"
    jwt_algorithm: str = "RS256"
    jwt_access_token_expire_minutes: int = 60

    embedding_model_name: str = "microsoft/codebert-base"
    embedding_dimension: int = 768

    max_repo_size_mb: int = 500
    max_files_per_repo: int = 5000
    clone_timeout_seconds: int = 300

    rate_limit_analyze_per_minute: int = 5
    rate_limit_bucket_capacity: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 5: Write app/main.py**

```python
from fastapi import FastAPI

from app.config import get_settings

settings = get_settings()

app = FastAPI(title="Repo Analyzer API", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

Create empty `backend/app/__init__.py`.

- [ ] **Step 6: Write pytest.ini**

`backend/pytest.ini`:
```ini
[pytest]
markers =
    integration: requires Postgres+pgvector and Redis running (docker compose up -d postgres redis)
    slow: loads the real CodeBERT model (first run downloads ~500MB)
testpaths = tests
pythonpath = .
asyncio_mode = auto
```

- [ ] **Step 7: Write .env.example**

`backend/.env.example`:
```
DATABASE_URL=postgresql+asyncpg://repoanalyzer:repoanalyzer@localhost:5432/repoanalyzer
REDIS_URL=redis://localhost:6379/0
JWT_PRIVATE_KEY_PATH=keys/jwt_private.pem
JWT_PUBLIC_KEY_PATH=keys/jwt_public.pem
JWT_ALGORITHM=RS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
EMBEDDING_MODEL_NAME=microsoft/codebert-base
MAX_REPO_SIZE_MB=500
MAX_FILES_PER_REPO=5000
RATE_LIMIT_ANALYZE_PER_MINUTE=5
```

- [ ] **Step 8: Write root .gitignore**

`.gitignore` (repo root):
```
__pycache__/
*.pyc
.pytest_cache/
.venv/
venv/
backend/keys/*.pem
backend/.env
.coverage
htmlcov/
*.egg-info/
```

- [ ] **Step 9: Run the test again, verify it passes**

Run: `pytest tests/unit/test_health.py -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "Scaffold FastAPI backend with config and health check"
```

---

### Task 2: Docker Compose for Postgres+pgvector and Redis

**Files:**
- Create: `docker-compose.yml` (root)

**Interfaces:**
- Produces: running `postgres` service (`pgvector/pgvector:pg16`) on `localhost:5432`, db `repoanalyzer`, user/pass `repoanalyzer`/`repoanalyzer`
- Produces: running `redis` service (`redis:7-alpine`) on `localhost:6379`

- [ ] **Step 1: Write docker-compose.yml**

```yaml
version: "3.9"

services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: repo-analyzer-postgres
    environment:
      POSTGRES_USER: repoanalyzer
      POSTGRES_PASSWORD: repoanalyzer
      POSTGRES_DB: repoanalyzer
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U repoanalyzer -d repoanalyzer"]
      interval: 5s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    container_name: repo-analyzer-redis
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  postgres_data:
```

- [ ] **Step 2: Bring the services up (requires Docker Desktop running)**

```bash
docker compose up -d postgres redis
docker compose ps
```
Expected: both services show `healthy`.

- [ ] **Step 3: Verify Postgres and the vector extension**

```bash
docker compose exec postgres psql -U repoanalyzer -d repoanalyzer -c "CREATE EXTENSION IF NOT EXISTS vector; SELECT 1;"
```
Expected: `CREATE EXTENSION` (or notice it exists) then `1`.

- [ ] **Step 4: Verify Redis**

```bash
docker compose exec redis redis-cli ping
```
Expected: `PONG`

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml
git commit -m "Add docker-compose for Postgres+pgvector and Redis"
```

---

### Task 3: Database models + Alembic migration

**Files:**
- Create: `backend/app/db/__init__.py`
- Create: `backend/app/db/base.py`
- Create: `backend/app/db/session.py`
- Create: `backend/app/db/models.py`
- Create: `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`, `backend/alembic/versions/0001_initial_schema.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/integration/__init__.py`
- Test: `backend/tests/integration/test_models.py`

**Interfaces:**
- Produces: `Base` (DeclarativeBase) in `app.db.base`
- Produces: `engine`, `async_session_maker`, `async def get_db() -> AsyncGenerator[AsyncSession, None]` in `app.db.session`
- Produces models in `app.db.models`: `User`, `ApiKey`, `Repo`, `RepoStatus`, `Job`, `JobStatus`, `CodeChunk`, `NodeType`
- Produces: `db_session` pytest fixture in `tests/conftest.py` (rolled back after each test)

- [ ] **Step 1: Write app/db/base.py**

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

Create empty `backend/app/db/__init__.py`.

- [ ] **Step 2: Write app/db/session.py**

```python
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, pool_size=20, max_overflow=10, pool_pre_ping=True)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session
```

- [ ] **Step 3: Write app/db/models.py**

```python
import enum
import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RepoStatus(str, enum.Enum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class NodeType(str, enum.Enum):
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    TEXT = "text"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    repos: Mapped[list["Repo"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    hashed_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="api_keys")


class Repo(Base):
    __tablename__ = "repos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(100), default="main", nullable=False)
    status: Mapped[RepoStatus] = mapped_column(
        Enum(RepoStatus, name="repo_status", values_callable=lambda e: [m.value for m in e]),
        default=RepoStatus.PENDING, nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    user: Mapped["User"] = relationship(back_populates="repos")
    jobs: Mapped[list["Job"]] = relationship(back_populates="repo", cascade="all, delete-orphan")
    chunks: Mapped[list["CodeChunk"]] = relationship(back_populates="repo", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("user_id", "url", name="uq_repo_user_url"),)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    repo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", values_callable=lambda e: [m.value for m in e]),
        default=JobStatus.PENDING, nullable=False,
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    skipped_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    repo: Mapped["Repo"] = relationship(back_populates="jobs")


class CodeChunk(Base):
    __tablename__ = "code_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    repo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    symbol_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    node_type: Mapped[NodeType] = mapped_column(
        Enum(NodeType, name="node_type", values_callable=lambda e: [m.value for m in e]), nullable=False
    )
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(768), nullable=False)
    content_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', content)", persisted=True), nullable=True
    )

    repo: Mapped["Repo"] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("ix_code_chunks_repo_id", "repo_id"),
        Index("ix_code_chunks_content_tsv", "content_tsv", postgresql_using="gin"),
    )
```

- [ ] **Step 4: Initialize Alembic with the async template**

```bash
cd backend
alembic init -t async alembic
```

- [ ] **Step 5: Edit alembic.ini**

Remove/comment the `sqlalchemy.url = ...` line (it will be set programmatically from `Settings`).

- [ ] **Step 6: Edit alembic/env.py**

Add near the top, after the existing imports:
```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db import models  # noqa: E402,F401
```

Then set:
```python
target_metadata = Base.metadata

_settings = get_settings()
config.set_main_option("sqlalchemy.url", _settings.database_url)
```
(Replace the existing `target_metadata = None` line; keep the rest of the generated async template as-is.)

- [ ] **Step 7: Generate the initial migration**

```bash
alembic revision --autogenerate -m "initial schema"
```

- [ ] **Step 8: Edit the generated migration file**

Open `backend/alembic/versions/<hash>_initial_schema.py` and rename it to `0001_initial_schema.py`. At the very top of `upgrade()`, before any `op.create_table` calls, add:
```python
op.execute("CREATE EXTENSION IF NOT EXISTS vector")
```
At the very end of `upgrade()`, after `code_chunks` is created, add:
```python
op.execute(
    "CREATE INDEX ix_code_chunks_embedding ON code_chunks "
    "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
)
```
In `downgrade()`, before dropping tables, add:
```python
op.execute("DROP INDEX IF EXISTS ix_code_chunks_embedding")
```

- [ ] **Step 9: Apply the migration**

```bash
alembic upgrade head
```
Expected: no errors; `docker compose exec postgres psql -U repoanalyzer -d repoanalyzer -c "\dt"` shows `users`, `api_keys`, `repos`, `jobs`, `code_chunks`.

- [ ] **Step 10: Write tests/conftest.py**

```python
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_maker


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    async with async_session_maker() as session:
        yield session
        await session.rollback()
```

Create empty `backend/tests/integration/__init__.py`.

- [ ] **Step 11: Write the test**

`backend/tests/integration/test_models.py`:
```python
import uuid

import pytest
from sqlalchemy import select

from app.db.models import CodeChunk, NodeType, Repo, RepoStatus, User

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_create_and_query_user(db_session):
    user = User(email=f"test-{uuid.uuid4()}@example.com", hashed_password="hashed")
    db_session.add(user)
    await db_session.flush()

    result = await db_session.execute(select(User).where(User.id == user.id))
    fetched = result.scalar_one()
    assert fetched.email == user.email


@pytest.mark.asyncio
async def test_code_chunk_vector_similarity_search(db_session):
    user = User(email=f"test-{uuid.uuid4()}@example.com", hashed_password="hashed")
    db_session.add(user)
    await db_session.flush()

    repo = Repo(user_id=user.id, url="https://github.com/example/repo", name="repo", status=RepoStatus.READY)
    db_session.add(repo)
    await db_session.flush()

    close_vector = [0.1] * 768
    far_vector = [0.9] * 768

    chunk_close = CodeChunk(
        repo_id=repo.id, file_path="a.py", symbol_name="foo", node_type=NodeType.FUNCTION,
        start_line=1, end_line=5, content="def foo(): pass", embedding=close_vector,
    )
    chunk_far = CodeChunk(
        repo_id=repo.id, file_path="b.py", symbol_name="bar", node_type=NodeType.FUNCTION,
        start_line=1, end_line=5, content="def bar(): pass", embedding=far_vector,
    )
    db_session.add_all([chunk_close, chunk_far])
    await db_session.flush()

    query_vector = [0.1] * 768
    result = await db_session.execute(
        select(CodeChunk).order_by(CodeChunk.embedding.cosine_distance(query_vector)).limit(1)
    )
    nearest = result.scalar_one()
    assert nearest.id == chunk_close.id
```

- [ ] **Step 12: Run it, verify it passes**

Run: `pytest -m integration tests/integration/test_models.py -v`
Expected: PASS (requires `docker compose up -d postgres redis` from Task 2 and migration from Step 9)

- [ ] **Step 13: Commit**

```bash
git add -A
git commit -m "Add database models, Alembic migration, and pgvector similarity test"
```

---

### Task 4: JWT RS256 + password hashing (security core)

**Files:**
- Create: `backend/scripts/generate_keys.py`
- Create: `backend/app/core/__init__.py`
- Create: `backend/app/core/security.py`
- Test: `backend/tests/unit/test_security.py`

**Interfaces:**
- Produces: `hash_password(password: str) -> str`, `verify_password(password: str, hashed: str) -> bool`
- Produces: `create_access_token(subject: str, expires_minutes: int | None = None) -> str`, `decode_access_token(token: str) -> dict`
- Produces: `generate_api_key() -> tuple[str, str]` (plaintext, hashed), `hash_api_key(key: str) -> str`

- [ ] **Step 1: Write the failing test**

`backend/tests/unit/test_security.py`:
```python
import pytest

from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_api_key,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_jwt_roundtrip():
    token = create_access_token(subject="user-123")
    payload = decode_access_token(token)
    assert payload["sub"] == "user-123"


def test_jwt_expired_token_rejected():
    token = create_access_token(subject="user-123", expires_minutes=-1)
    with pytest.raises(Exception):
        decode_access_token(token)


def test_generate_api_key_is_unique_and_hashable():
    key1, hash1 = generate_api_key()
    key2, hash2 = generate_api_key()
    assert key1 != key2
    assert key1.startswith("ra_")
    assert hash1 != key1
```

- [ ] **Step 2: Run it, verify it fails**

Run: `pytest tests/unit/test_security.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.core'`)

- [ ] **Step 3: Generate a local JWT keypair**

`backend/scripts/generate_keys.py`:
```python
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KEYS_DIR = Path(__file__).resolve().parent.parent / "keys"


def main() -> None:
    KEYS_DIR.mkdir(exist_ok=True)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    (KEYS_DIR / "jwt_private.pem").write_bytes(private_bytes)
    (KEYS_DIR / "jwt_public.pem").write_bytes(public_bytes)
    print(f"Wrote keys to {KEYS_DIR}")


if __name__ == "__main__":
    main()
```

Run it: `python scripts/generate_keys.py` (from `backend/`). This creates `backend/keys/jwt_private.pem` and `jwt_public.pem` — gitignored, must be regenerated per environment.

- [ ] **Step 4: Write app/core/security.py**

```python
import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import jwt
from passlib.context import CryptContext

from app.config import get_settings

settings = get_settings()
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _pwd_context.verify(password, hashed)


@lru_cache
def _private_key() -> str:
    return (BACKEND_ROOT / settings.jwt_private_key_path).read_text()


@lru_cache
def _public_key() -> str:
    return (BACKEND_ROOT / settings.jwt_public_key_path).read_text()


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes if expires_minutes is not None else settings.jwt_access_token_expire_minutes
    )
    payload = {"sub": subject, "exp": expire, "iat": datetime.now(timezone.utc)}
    return jwt.encode(payload, _private_key(), algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, _public_key(), algorithms=[settings.jwt_algorithm])


def generate_api_key() -> tuple[str, str]:
    plaintext = f"ra_{secrets.token_urlsafe(32)}"
    return plaintext, hash_api_key(plaintext)


def hash_api_key(key: str) -> str:
    return _pwd_context.hash(key)
```

Create empty `backend/app/core/__init__.py`.

- [ ] **Step 5: Run the test again, verify it passes**

Run: `pytest tests/unit/test_security.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add JWT RS256 auth and password/API-key hashing"
```

---

### Task 5: Auth API (register, login, current-user, API keys)

**Files:**
- Create: `backend/app/schemas/__init__.py`
- Create: `backend/app/schemas/auth.py`
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/api/deps.py`
- Create: `backend/app/api/routes/__init__.py`
- Create: `backend/app/api/routes/auth.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/test_auth_api.py`

**Interfaces:**
- Consumes: `hash_password`, `verify_password`, `create_access_token`, `generate_api_key` from `app.core.security` (Task 4); `User`, `ApiKey` from `app.db.models` (Task 3); `get_db` from `app.db.session` (Task 3)
- Produces: `get_current_user(...) -> User` dependency in `app.api.deps`, importable as `from app.api.deps import get_current_user`
- Produces routes: `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me`, `POST /api/v1/auth/api-keys`

- [ ] **Step 1: Write the schemas**

`backend/app/schemas/auth.py`:
```python
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime


class ApiKeyCreated(ApiKeyResponse):
    key: str
```

Create empty `backend/app/schemas/__init__.py`.

- [ ] **Step 2: Write app/api/deps.py**

```python
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.models import User
from app.db.session import get_db

_bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = payload["sub"]
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user
```

Create empty `backend/app/api/__init__.py` and `backend/app/api/routes/__init__.py`.

- [ ] **Step 3: Write app/api/routes/auth.py**

```python
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.security import create_access_token, generate_api_key, hash_password, verify_password
from app.db.models import ApiKey, User
from app.db.session import get_db
from app.schemas.auth import (
    ApiKeyCreate,
    ApiKeyCreated,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, db: Annotated[AsyncSession, Depends(get_db)]) -> User:
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(email=payload.email, hashed_password=hash_password(payload.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLogin, db: Annotated[AsyncSession, Depends(get_db)]) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token(subject=str(user.id))
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    return current_user


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiKeyCreated:
    plaintext, hashed = generate_api_key()
    api_key = ApiKey(user_id=current_user.id, hashed_key=hashed, name=payload.name)
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    return ApiKeyCreated(id=api_key.id, name=api_key.name, created_at=api_key.created_at, key=plaintext)
```

- [ ] **Step 4: Wire the router into main.py**

Modify `backend/app/main.py`, add after the `app = FastAPI(...)` line:
```python
from app.api.routes import auth

app.include_router(auth.router)
```

- [ ] **Step 5: Write the test**

`backend/tests/integration/test_auth_api.py`:
```python
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_register_login_and_me_flow():
    email = f"user-{uuid.uuid4()}@example.com"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        register_resp = await client.post(
            "/api/v1/auth/register", json={"email": email, "password": "supersecret123"}
        )
        assert register_resp.status_code == 201

        login_resp = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "supersecret123"}
        )
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]

        me_resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_resp.status_code == 200
        assert me_resp.json()["email"] == email


@pytest.mark.asyncio
async def test_login_with_wrong_password_rejected():
    email = f"user-{uuid.uuid4()}@example.com"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
        resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_api_key_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/auth/api-keys", json={"name": "ci-key"})
        assert resp.status_code in (401, 403)
```

- [ ] **Step 6: Run it, verify it passes**

Run: `pytest -m integration tests/integration/test_auth_api.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Add auth API: register, login, current user, API keys"
```

---

### Task 6: Redis token-bucket rate limiter

**Files:**
- Create: `backend/app/core/rate_limit.py`
- Test: `backend/tests/integration/test_rate_limit.py`

**Interfaces:**
- Produces: `async def check_token_bucket(key: str, capacity: int, refill_per_minute: int) -> bool`
- Produces: `async def enforce_analyze_rate_limit(current_user: Annotated[User, Depends(get_current_user)]) -> User` dependency, consumed by Task 12's `POST /repos/analyze`

- [ ] **Step 1: Write the failing test**

`backend/tests/integration/test_rate_limit.py`:
```python
import asyncio
import uuid

import pytest

from app.core.rate_limit import check_token_bucket

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_token_bucket_allows_up_to_capacity_then_blocks():
    key = f"test:{uuid.uuid4()}"
    for _ in range(3):
        assert await check_token_bucket(key, capacity=3, refill_per_minute=0) is True
    assert await check_token_bucket(key, capacity=3, refill_per_minute=0) is False


@pytest.mark.asyncio
async def test_token_bucket_refills_over_time():
    key = f"test:{uuid.uuid4()}"
    assert await check_token_bucket(key, capacity=1, refill_per_minute=60) is True
    assert await check_token_bucket(key, capacity=1, refill_per_minute=60) is False
    await asyncio.sleep(1.1)
    assert await check_token_bucket(key, capacity=1, refill_per_minute=60) is True
```

- [ ] **Step 2: Run it, verify it fails**

Run: `pytest -m integration tests/integration/test_rate_limit.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.core.rate_limit'`)

- [ ] **Step 3: Write app/core/rate_limit.py**

```python
import time
from typing import Annotated

import redis.asyncio as redis
from fastapi import Depends, HTTPException, status

from app.api.deps import get_current_user
from app.config import get_settings
from app.db.models import User

settings = get_settings()

_redis_client: redis.Redis | None = None

_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_per_sec = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local bucket = redis.call('HMGET', key, 'tokens', 'updated_at')
local tokens = tonumber(bucket[1])
local updated_at = tonumber(bucket[2])

if tokens == nil then
    tokens = capacity
    updated_at = now
end

local elapsed = math.max(0, now - updated_at)
tokens = math.min(capacity, tokens + elapsed * refill_per_sec)

local allowed = 0
if tokens >= requested then
    tokens = tokens - requested
    allowed = 1
end

redis.call('HMSET', key, 'tokens', tokens, 'updated_at', now)
redis.call('EXPIRE', key, 3600)

return allowed
"""


def get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def check_token_bucket(key: str, capacity: int, refill_per_minute: int) -> bool:
    client = get_redis_client()
    refill_per_sec = refill_per_minute / 60.0
    allowed = await client.eval(_TOKEN_BUCKET_LUA, 1, key, capacity, refill_per_sec, time.time(), 1)
    return bool(allowed)


async def enforce_analyze_rate_limit(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    allowed = await check_token_bucket(
        key=f"rate_limit:analyze:{current_user.id}",
        capacity=settings.rate_limit_bucket_capacity,
        refill_per_minute=settings.rate_limit_analyze_per_minute,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for repo analysis requests. Try again shortly.",
        )
    return current_user
```

- [ ] **Step 4: Run it, verify it passes**

Run: `pytest -m integration tests/integration/test_rate_limit.py -v`
Expected: PASS (requires Redis running)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add Redis token-bucket rate limiter"
```

---

### Task 7: Tree-sitter AST parser registry

**Files:**
- Create: `backend/app/core/ast_parser.py`
- Test: `backend/tests/unit/test_ast_parser.py`

**Interfaces:**
- Produces: `language_for_path(file_path: str) -> str | None`
- Produces: `@dataclass ParsedSymbol(name: str, node_type: str, start_line: int, end_line: int, content: str)` — `node_type` is `"function"` or `"class"`
- Produces: `parse_symbols(source_code: str, language: str) -> list[ParsedSymbol]`

- [ ] **Step 1: Write the failing test**

`backend/tests/unit/test_ast_parser.py`:
```python
from app.core.ast_parser import language_for_path, parse_symbols


def test_language_for_path_detects_known_extensions():
    assert language_for_path("app/main.py") == "python"
    assert language_for_path("src/index.ts") == "typescript"
    assert language_for_path("README.md") is None


def test_parse_symbols_extracts_python_function_and_class():
    source = """
def add(a, b):
    return a + b


class Calculator:
    def multiply(self, a, b):
        return a * b
"""
    symbols = parse_symbols(source, "python")
    names = {s.name for s in symbols}
    assert "add" in names
    assert "Calculator" in names
    assert "multiply" in names

    add_symbol = next(s for s in symbols if s.name == "add")
    assert add_symbol.node_type == "function"
    assert "return a + b" in add_symbol.content


def test_parse_symbols_extracts_go_function():
    source = """
package main

func Add(a int, b int) int {
    return a + b
}
"""
    symbols = parse_symbols(source, "go")
    assert any(s.name == "Add" for s in symbols)


def test_parse_symbols_handles_syntax_errors_gracefully():
    broken_source = "def broken(:\n    this is not valid python"
    symbols = parse_symbols(broken_source, "python")
    assert isinstance(symbols, list)
```

- [ ] **Step 2: Run it, verify it fails**

Run: `pytest tests/unit/test_ast_parser.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write app/core/ast_parser.py**

```python
from dataclasses import dataclass

from tree_sitter import Node
from tree_sitter_languages import get_parser

SUPPORTED_LANGUAGES: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".java": "java",
}

_DEFINITION_NODE_TYPES: dict[str, set[str]] = {
    "python": {"function_definition", "class_definition"},
    "javascript": {"function_declaration", "class_declaration", "method_definition"},
    "typescript": {"function_declaration", "class_declaration", "method_definition"},
    "tsx": {"function_declaration", "class_declaration", "method_definition"},
    "go": {"function_declaration", "method_declaration", "type_declaration"},
    "java": {"class_declaration", "method_declaration", "interface_declaration"},
}


@dataclass
class ParsedSymbol:
    name: str
    node_type: str
    start_line: int
    end_line: int
    content: str


def language_for_path(file_path: str) -> str | None:
    for ext, lang in SUPPORTED_LANGUAGES.items():
        if file_path.endswith(ext):
            return lang
    return None


def _symbol_name(node: Node, source: bytes) -> str:
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return source[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
    return "<anonymous>"


def parse_symbols(source_code: str, language: str) -> list[ParsedSymbol]:
    parser = get_parser(language)
    source_bytes = source_code.encode("utf-8")
    tree = parser.parse(source_bytes)

    definition_types = _DEFINITION_NODE_TYPES.get(language, set())
    symbols: list[ParsedSymbol] = []

    def visit(node: Node) -> None:
        if node.type in definition_types:
            symbols.append(
                ParsedSymbol(
                    name=_symbol_name(node, source_bytes),
                    node_type="class" if ("class" in node.type or "interface" in node.type) else "function",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    content=source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace"),
                )
            )
        for child in node.children:
            visit(child)

    visit(tree.root_node)
    return symbols
```

- [ ] **Step 4: Run it, verify it passes**

Run: `pytest tests/unit/test_ast_parser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add Tree-sitter AST parser registry"
```

---

### Task 8: Chunker (AST-aware + sliding-window fallback)

**Files:**
- Create: `backend/app/core/chunker.py`
- Test: `backend/tests/unit/test_chunker.py`

**Interfaces:**
- Consumes: `language_for_path`, `parse_symbols` from `app.core.ast_parser` (Task 7)
- Produces: `@dataclass Chunk(file_path: str, symbol_name: str | None, node_type: str, start_line: int, end_line: int, content: str)` — `node_type` is `"function"`, `"class"`, or `"text"`
- Produces: `chunk_file(file_path: str, source_code: str) -> list[Chunk]`

- [ ] **Step 1: Write the failing test**

`backend/tests/unit/test_chunker.py`:
```python
from app.core.chunker import chunk_file


def test_chunk_file_uses_ast_for_python():
    source = "def foo():\n    return 1\n"
    chunks = chunk_file("app.py", source)
    assert len(chunks) == 1
    assert chunks[0].symbol_name == "foo"
    assert chunks[0].node_type == "function"


def test_chunk_file_falls_back_to_sliding_window_for_unsupported_language():
    source = "x" * 5000
    chunks = chunk_file("data.rs", source)
    assert len(chunks) > 1
    assert all(c.node_type == "text" for c in chunks)
    assert all(len(c.content) <= 2000 for c in chunks)


def test_chunk_file_falls_back_when_no_symbols_found():
    source = "x = 1\ny = 2\n"
    chunks = chunk_file("consts.py", source)
    assert len(chunks) >= 1
    assert chunks[0].node_type == "text"


def test_chunk_file_handles_empty_file():
    assert chunk_file("empty.py", "") == []
```

- [ ] **Step 2: Run it, verify it fails**

Run: `pytest tests/unit/test_chunker.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write app/core/chunker.py**

```python
from dataclasses import dataclass

from app.core.ast_parser import language_for_path, parse_symbols

MAX_CHUNK_CHARS = 4000
FALLBACK_WINDOW_CHARS = 2000
FALLBACK_OVERLAP_CHARS = 200


@dataclass
class Chunk:
    file_path: str
    symbol_name: str | None
    node_type: str
    start_line: int
    end_line: int
    content: str


def chunk_file(file_path: str, source_code: str) -> list[Chunk]:
    if not source_code.strip():
        return []

    language = language_for_path(file_path)
    if language is not None:
        symbols = parse_symbols(source_code, language)
        if symbols:
            return [
                Chunk(
                    file_path=file_path,
                    symbol_name=symbol.name,
                    node_type=symbol.node_type,
                    start_line=symbol.start_line,
                    end_line=symbol.end_line,
                    content=symbol.content[:MAX_CHUNK_CHARS],
                )
                for symbol in symbols
            ]

    return _sliding_window_chunks(file_path, source_code)


def _sliding_window_chunks(file_path: str, source_code: str) -> list[Chunk]:
    lines = source_code.splitlines()
    if not lines:
        return []

    line_starts: list[int] = []
    running = 0
    for line in lines:
        line_starts.append(running)
        running += len(line) + 1

    full_text = "\n".join(lines)
    step_chars = FALLBACK_WINDOW_CHARS - FALLBACK_OVERLAP_CHARS

    chunks: list[Chunk] = []
    pos = 0
    while pos < len(full_text):
        window = full_text[pos:pos + FALLBACK_WINDOW_CHARS]
        chunks.append(
            Chunk(
                file_path=file_path,
                symbol_name=None,
                node_type="text",
                start_line=_line_for_offset(line_starts, pos),
                end_line=_line_for_offset(line_starts, pos + len(window)),
                content=window,
            )
        )
        if pos + FALLBACK_WINDOW_CHARS >= len(full_text):
            break
        pos += step_chars

    return chunks


def _line_for_offset(line_starts: list[int], offset: int) -> int:
    line = 1
    for i, start in enumerate(line_starts):
        if start <= offset:
            line = i + 1
        else:
            break
    return line
```

- [ ] **Step 4: Run it, verify it passes**

Run: `pytest tests/unit/test_chunker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add AST-aware chunker with sliding-window fallback"
```

---

### Task 9: Embeddings (CodeBERT wrapper)

**Files:**
- Create: `backend/app/core/embeddings.py`
- Test: `backend/tests/unit/test_embeddings.py`

**Interfaces:**
- Produces: `embed_text(text: str) -> list[float]`, `embed_texts(texts: list[str], batch_size: int = 8) -> list[list[float]]` — both return 768-dim vectors matching `Settings.embedding_dimension`

- [ ] **Step 1: Write the failing test**

`backend/tests/unit/test_embeddings.py`:
```python
import math

import pytest

from app.config import get_settings
from app.core.embeddings import embed_text, embed_texts

pytestmark = pytest.mark.slow


def test_embed_text_returns_correct_dimension():
    embedding = embed_text("def add(a, b): return a + b")
    assert len(embedding) == get_settings().embedding_dimension


def test_embed_texts_batch_matches_individual_count():
    texts = ["def foo(): pass", "class Bar: pass", "x = 1"]
    embeddings = embed_texts(texts)
    assert len(embeddings) == 3
    assert all(len(e) == get_settings().embedding_dimension for e in embeddings)


def test_embed_texts_empty_list_returns_empty():
    assert embed_texts([]) == []


def test_similar_code_has_higher_cosine_similarity_than_dissimilar():
    def cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        return dot / (norm_a * norm_b)

    e1 = embed_text("def add(a, b): return a + b")
    e2 = embed_text("def sum_values(x, y): return x + y")
    e3 = embed_text("class DatabaseConnection: pass")

    assert cosine(e1, e2) > cosine(e1, e3)
```

- [ ] **Step 2: Run it, verify it fails**

Run: `pytest -m slow tests/unit/test_embeddings.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write app/core/embeddings.py**

```python
from functools import lru_cache

import torch
from transformers import AutoModel, AutoTokenizer

from app.config import get_settings

settings = get_settings()


@lru_cache
def _tokenizer():
    return AutoTokenizer.from_pretrained(settings.embedding_model_name)


@lru_cache
def _model():
    model = AutoModel.from_pretrained(settings.embedding_model_name)
    model.eval()
    return model


def embed_texts(texts: list[str], batch_size: int = 8) -> list[list[float]]:
    if not texts:
        return []

    tokenizer = _tokenizer()
    model = _model()
    all_embeddings: list[list[float]] = []

    with torch.no_grad():
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            inputs = tokenizer(batch, padding=True, truncation=True, max_length=512, return_tensors="pt")
            outputs = model(**inputs)
            token_embeddings = outputs.last_hidden_state
            attention_mask = inputs["attention_mask"].unsqueeze(-1).expand(token_embeddings.size()).float()
            summed = torch.sum(token_embeddings * attention_mask, dim=1)
            counts = torch.clamp(attention_mask.sum(dim=1), min=1e-9)
            mean_pooled = summed / counts
            all_embeddings.extend(mean_pooled.tolist())

    return all_embeddings


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]
```

- [ ] **Step 4: Run it, verify it passes**

Run: `pytest -m slow tests/unit/test_embeddings.py -v`
Expected: PASS (first run downloads `microsoft/codebert-base`, ~500MB, cached afterward)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add CodeBERT embedding wrapper"
```

---

### Task 10: Ingestion pipeline (clone, walk, parse, chunk, embed)

**Files:**
- Create: `backend/app/core/ingestion.py`
- Create: `backend/tests/fixtures/sample_repo/main.py`
- Create: `backend/tests/fixtures/sample_repo/utils.py`
- Create: `backend/tests/fixtures/sample_repo/README.md`
- Test: `backend/tests/unit/test_ingestion.py`

**Interfaces:**
- Consumes: `chunk_file`, `Chunk` from `app.core.chunker` (Task 8); `embed_texts` from `app.core.embeddings` (Task 9)
- Produces: `clone_repo(url: str, dest_dir: Path, max_size_mb: int, timeout_seconds: int) -> Path`, raising `CloneError` or `RepoTooLargeError`
- Produces: `walk_and_chunk(root_dir: Path, max_files: int) -> tuple[list[Chunk], int, int]` (chunks, files_processed, files_skipped)
- Produces: `embed_chunks(chunks: list[Chunk], batch_size: int = 8) -> list[ChunkWithEmbedding]`
- Produces: `@dataclass ChunkWithEmbedding(chunk: Chunk, embedding: list[float])`, consumed by Task 11's worker task

- [ ] **Step 1: Create the fixture repo files**

`backend/tests/fixtures/sample_repo/main.py`:
```python
def greet(name):
    return f"Hello, {name}!"


class Greeter:
    def __init__(self, default_name="World"):
        self.default_name = default_name

    def greet_default(self):
        return greet(self.default_name)
```

`backend/tests/fixtures/sample_repo/utils.py`:
```python
def add(a, b):
    return a + b


def subtract(a, b):
    return a - b
```

`backend/tests/fixtures/sample_repo/README.md`:
```
# Sample Repo

This is a fixture repository used for ingestion pipeline tests.
```

- [ ] **Step 2: Write the failing test**

`backend/tests/unit/test_ingestion.py`:
```python
from pathlib import Path

import pytest

from app.core.ingestion import ingest_local_directory, walk_and_chunk

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "sample_repo"


def test_walk_and_chunk_processes_all_fixture_files():
    chunks, processed, skipped = walk_and_chunk(FIXTURE_DIR, max_files=100)
    assert processed == 3
    assert skipped == 0
    symbol_names = {c.symbol_name for c in chunks if c.symbol_name}
    assert "greet" in symbol_names
    assert "Greeter" in symbol_names
    assert "add" in symbol_names


def test_walk_and_chunk_respects_max_files():
    chunks, processed, skipped = walk_and_chunk(FIXTURE_DIR, max_files=1)
    assert processed == 1


@pytest.mark.slow
def test_ingest_local_directory_produces_embeddings():
    result = ingest_local_directory(FIXTURE_DIR, max_files=100)
    assert result.files_processed == 3
    assert len(result.chunks) > 0
    assert all(len(cwe.embedding) == 768 for cwe in result.chunks)
```

- [ ] **Step 3: Run it, verify it fails**

Run: `pytest tests/unit/test_ingestion.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 4: Write app/core/ingestion.py**

```python
from dataclasses import dataclass
from pathlib import Path

import git

from app.core.chunker import Chunk, chunk_file
from app.core.embeddings import embed_texts

EXCLUDED_DIR_PATTERNS = {
    ".git", "node_modules", "dist", "build", "__pycache__", ".venv", "venv",
    ".next", "target", "vendor", ".pytest_cache",
}
MAX_FILE_SIZE_BYTES = 1_000_000


@dataclass
class ChunkWithEmbedding:
    chunk: Chunk
    embedding: list[float]


@dataclass
class IngestionResult:
    chunks: list[ChunkWithEmbedding]
    files_processed: int
    files_skipped: int


class RepoTooLargeError(Exception):
    pass


class CloneError(Exception):
    pass


def clone_repo(url: str, dest_dir: Path, max_size_mb: int, timeout_seconds: int) -> Path:
    try:
        git.Repo.clone_from(url, dest_dir, depth=1, single_branch=True)
    except git.GitCommandError as exc:
        raise CloneError(f"Failed to clone {url}: {exc}") from exc

    total_size_mb = sum(f.stat().st_size for f in dest_dir.rglob("*") if f.is_file()) / (1024 * 1024)
    if total_size_mb > max_size_mb:
        raise RepoTooLargeError(f"Repo size {total_size_mb:.1f}MB exceeds cap of {max_size_mb}MB")

    return dest_dir


def _should_skip_dir(dir_name: str) -> bool:
    return dir_name in EXCLUDED_DIR_PATTERNS or dir_name.startswith(".")


def walk_and_chunk(root_dir: Path, max_files: int) -> tuple[list[Chunk], int, int]:
    all_chunks: list[Chunk] = []
    files_processed = 0
    files_skipped = 0

    for path in sorted(root_dir.rglob("*")):
        if path.is_dir():
            continue
        if any(_should_skip_dir(part) for part in path.relative_to(root_dir).parts[:-1]):
            continue
        if files_processed + files_skipped >= max_files:
            break
        if path.stat().st_size > MAX_FILE_SIZE_BYTES:
            files_skipped += 1
            continue

        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            files_skipped += 1
            continue

        try:
            relative_path = str(path.relative_to(root_dir)).replace("\\", "/")
            all_chunks.extend(chunk_file(relative_path, source))
            files_processed += 1
        except Exception:
            files_skipped += 1
            continue

    return all_chunks, files_processed, files_skipped


def embed_chunks(chunks: list[Chunk], batch_size: int = 8) -> list[ChunkWithEmbedding]:
    if not chunks:
        return []
    embeddings = embed_texts([c.content for c in chunks], batch_size=batch_size)
    return [ChunkWithEmbedding(chunk=c, embedding=e) for c, e in zip(chunks, embeddings)]


def ingest_local_directory(root_dir: Path, max_files: int) -> IngestionResult:
    chunks, processed, skipped = walk_and_chunk(root_dir, max_files)
    embedded = embed_chunks(chunks)
    return IngestionResult(chunks=embedded, files_processed=processed, files_skipped=skipped)
```

- [ ] **Step 5: Run it, verify it passes**

Run: `pytest tests/unit/test_ingestion.py -v` (fast tests only) and `pytest -m slow tests/unit/test_ingestion.py -v` (embedding test)
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add repo ingestion pipeline: clone, walk, chunk, embed"
```

---

### Task 11: ARQ worker wiring + job pipeline orchestration

**Files:**
- Create: `backend/app/workers/__init__.py`
- Create: `backend/app/workers/tasks.py`
- Create: `backend/app/workers/settings.py`
- Test: `backend/tests/integration/test_worker_tasks.py`

**Interfaces:**
- Consumes: `clone_repo`, `walk_and_chunk`, `embed_chunks`, `CloneError`, `RepoTooLargeError` from `app.core.ingestion` (Task 10); `Job`, `JobStatus`, `Repo`, `RepoStatus`, `CodeChunk`, `NodeType` from `app.db.models` (Task 3); `async_session_maker` from `app.db.session` (Task 3)
- Produces: `async def analyze_repo(ctx: dict, job_id: str) -> None` — the ARQ task function, registered by name `"analyze_repo"`, consumed by Task 12's `POST /repos/analyze` via `pool.enqueue_job("analyze_repo", ...)`
- Produces: `WorkerSettings` class in `app.workers.settings` with `functions = [analyze_repo]`, consumed by the `arq` CLI in Task 15's Dockerfile/compose command

- [ ] **Step 1: Write app/workers/tasks.py**

```python
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.config import get_settings
from app.core.ingestion import CloneError, RepoTooLargeError, clone_repo, embed_chunks, walk_and_chunk
from app.db.models import CodeChunk, Job, JobStatus, NodeType, Repo, RepoStatus
from app.db.session import async_session_maker

settings = get_settings()


async def analyze_repo(ctx: dict, job_id: str) -> None:
    async with async_session_maker() as db:
        job = await db.get(Job, UUID(job_id))
        if job is None:
            return

        repo = await db.get(Repo, job.repo_id)
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        await db.commit()

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                clone_path = clone_repo(
                    repo.url, Path(tmp_dir) / "repo",
                    max_size_mb=settings.max_repo_size_mb,
                    timeout_seconds=settings.clone_timeout_seconds,
                )
                chunks, _processed, skipped = walk_and_chunk(clone_path, max_files=settings.max_files_per_repo)
                job.progress = 50
                await db.commit()

                embedded = embed_chunks(chunks)
                job.progress = 90
                await db.commit()

                for item in embedded:
                    db.add(
                        CodeChunk(
                            repo_id=repo.id,
                            file_path=item.chunk.file_path,
                            symbol_name=item.chunk.symbol_name,
                            node_type=NodeType(item.chunk.node_type),
                            start_line=item.chunk.start_line,
                            end_line=item.chunk.end_line,
                            content=item.chunk.content,
                            embedding=item.embedding,
                        )
                    )

                job.skipped_files = skipped
                job.status = JobStatus.COMPLETED
                job.progress = 100
                job.finished_at = datetime.now(timezone.utc)
                repo.status = RepoStatus.READY
                await db.commit()

        except (CloneError, RepoTooLargeError) as exc:
            job.status = JobStatus.FAILED
            job.error_message = str(exc)
            job.finished_at = datetime.now(timezone.utc)
            repo.status = RepoStatus.FAILED
            await db.commit()
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error_message = f"Unexpected error: {exc}"
            job.finished_at = datetime.now(timezone.utc)
            repo.status = RepoStatus.FAILED
            await db.commit()
```

- [ ] **Step 2: Write app/workers/settings.py**

```python
from arq.connections import RedisSettings

from app.config import get_settings
from app.workers.tasks import analyze_repo

settings = get_settings()


class WorkerSettings:
    functions = [analyze_repo]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    job_timeout = 600
    max_jobs = 10
```

Create empty `backend/app/workers/__init__.py`.

- [ ] **Step 3: Write the test**

`backend/tests/integration/test_worker_tasks.py`:
```python
import shutil
import uuid
from pathlib import Path

import git
import pytest
from sqlalchemy import select

from app.db.models import CodeChunk, Job, JobStatus, Repo, RepoStatus, User
from app.db.session import async_session_maker
from app.workers.tasks import analyze_repo

pytestmark = [pytest.mark.integration, pytest.mark.slow]

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "sample_repo"


@pytest.fixture
def local_git_repo_url(tmp_path):
    repo_dir = tmp_path / "local_repo"
    shutil.copytree(FIXTURE_DIR, repo_dir)
    repo = git.Repo.init(repo_dir, initial_branch="main")
    repo.index.add([str(p) for p in repo_dir.rglob("*") if p.is_file()])
    repo.index.commit("initial commit")
    yield str(repo_dir)


@pytest.mark.asyncio
async def test_analyze_repo_task_completes_and_stores_chunks(local_git_repo_url):
    async with async_session_maker() as db:
        user = User(email=f"worker-{uuid.uuid4()}@example.com", hashed_password="hashed")
        db.add(user)
        await db.flush()

        repo = Repo(user_id=user.id, url=local_git_repo_url, name="local-repo", status=RepoStatus.PENDING)
        db.add(repo)
        await db.flush()

        job = Job(repo_id=repo.id, status=JobStatus.PENDING)
        db.add(job)
        await db.commit()
        job_id = str(job.id)
        repo_id = repo.id
        user_id = user.id

    await analyze_repo({}, job_id)

    async with async_session_maker() as db:
        refreshed_job = await db.get(Job, uuid.UUID(job_id))
        assert refreshed_job.status == JobStatus.COMPLETED
        assert refreshed_job.progress == 100

        result = await db.execute(select(CodeChunk).where(CodeChunk.repo_id == repo_id))
        chunks = result.scalars().all()
        assert len(chunks) > 0
        assert any(c.symbol_name == "greet" for c in chunks)

        for chunk in chunks:
            await db.delete(chunk)
        await db.delete(refreshed_job)
        refreshed_repo = await db.get(Repo, repo_id)
        await db.delete(refreshed_repo)
        refreshed_user = await db.get(User, user_id)
        await db.delete(refreshed_user)
        await db.commit()


@pytest.mark.asyncio
async def test_analyze_repo_task_marks_failed_on_bad_url():
    async with async_session_maker() as db:
        user = User(email=f"worker-{uuid.uuid4()}@example.com", hashed_password="hashed")
        db.add(user)
        await db.flush()

        repo = Repo(user_id=user.id, url="/nonexistent/path/to/repo", name="bad-repo", status=RepoStatus.PENDING)
        db.add(repo)
        await db.flush()

        job = Job(repo_id=repo.id, status=JobStatus.PENDING)
        db.add(job)
        await db.commit()
        job_id = str(job.id)
        repo_id = repo.id
        user_id = user.id

    await analyze_repo({}, job_id)

    async with async_session_maker() as db:
        refreshed_job = await db.get(Job, uuid.UUID(job_id))
        assert refreshed_job.status == JobStatus.FAILED
        assert refreshed_job.error_message is not None

        await db.delete(refreshed_job)
        refreshed_repo = await db.get(Repo, repo_id)
        await db.delete(refreshed_repo)
        refreshed_user = await db.get(User, user_id)
        await db.delete(refreshed_user)
        await db.commit()
```

- [ ] **Step 4: Run it, verify it passes**

Run: `pytest -m "integration and slow" tests/integration/test_worker_tasks.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add ARQ worker task: full analyze_repo pipeline"
```

---

### Task 12: Repos & Jobs API

**Files:**
- Create: `backend/app/core/arq_pool.py`
- Create: `backend/app/schemas/repos.py`
- Create: `backend/app/api/routes/repos.py`
- Create: `backend/app/api/routes/jobs.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/test_repos_api.py`

**Interfaces:**
- Consumes: `enforce_analyze_rate_limit` from `app.core.rate_limit` (Task 6); `get_current_user` from `app.api.deps` (Task 5); `Repo`, `Job` from `app.db.models` (Task 3)
- Produces: `async def get_arq_pool() -> ArqRedis` in `app.core.arq_pool`
- Produces routes: `POST /api/v1/repos/analyze` (202, returns `{repo_id, job_id}`), `GET /api/v1/jobs/{job_id}`

- [ ] **Step 1: Write app/core/arq_pool.py**

```python
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import get_settings

settings = get_settings()

_pool: ArqRedis | None = None


async def get_arq_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _pool
```

- [ ] **Step 2: Write app/schemas/repos.py**

```python
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, HttpUrl


class RepoAnalyzeRequest(BaseModel):
    repo_url: HttpUrl


class RepoAnalyzeResponse(BaseModel):
    repo_id: uuid.UUID
    job_id: uuid.UUID


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repo_id: uuid.UUID
    status: str
    progress: int
    error_message: str | None
    skipped_files: int
    started_at: datetime | None
    finished_at: datetime | None
```

- [ ] **Step 3: Write app/api/routes/repos.py**

```python
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.arq_pool import get_arq_pool
from app.core.rate_limit import enforce_analyze_rate_limit
from app.db.models import Job, Repo, RepoStatus, User
from app.db.session import get_db
from app.schemas.repos import RepoAnalyzeRequest, RepoAnalyzeResponse

router = APIRouter(prefix="/api/v1/repos", tags=["repos"])


@router.post("/analyze", response_model=RepoAnalyzeResponse, status_code=status.HTTP_202_ACCEPTED)
async def analyze_repo_endpoint(
    payload: RepoAnalyzeRequest,
    current_user: Annotated[User, Depends(enforce_analyze_rate_limit)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RepoAnalyzeResponse:
    url_str = str(payload.repo_url)
    existing = await db.execute(select(Repo).where(Repo.user_id == current_user.id, Repo.url == url_str))
    repo = existing.scalar_one_or_none()
    if repo is None:
        repo = Repo(
            user_id=current_user.id,
            url=url_str,
            name=url_str.rstrip("/").rsplit("/", 1)[-1],
            status=RepoStatus.PENDING,
        )
        db.add(repo)
        await db.flush()

    job = Job(repo_id=repo.id)
    db.add(job)
    await db.commit()
    await db.refresh(job)

    pool = await get_arq_pool()
    await pool.enqueue_job("analyze_repo", str(job.id))

    return RepoAnalyzeResponse(repo_id=repo.id, job_id=job.id)
```

- [ ] **Step 4: Write app/api/routes/jobs.py**

```python
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import Job, User
from app.db.session import get_db
from app.schemas.repos import JobResponse

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Job:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job
```

- [ ] **Step 5: Wire the routers into main.py**

Modify `backend/app/main.py`, extend the import and includes:
```python
from app.api.routes import auth, jobs, repos

app.include_router(auth.router)
app.include_router(repos.router)
app.include_router(jobs.router)
```

- [ ] **Step 6: Write the test**

`backend/tests/integration/test_repos_api.py`:
```python
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

pytestmark = pytest.mark.integration


async def _register_and_login(client: AsyncClient) -> str:
    email = f"repos-{uuid.uuid4()}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
    login_resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
    return login_resp.json()["access_token"]


@pytest.mark.asyncio
async def test_analyze_endpoint_creates_job_and_returns_202():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        resp = await client.post(
            "/api/v1/repos/analyze",
            json={"repo_url": "https://github.com/octocat/Hello-World"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert "repo_id" in body
        assert "job_id" in body

        job_resp = await client.get(f"/api/v1/jobs/{body['job_id']}", headers={"Authorization": f"Bearer {token}"})
        assert job_resp.status_code == 200
        assert job_resp.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_analyze_endpoint_rate_limited_after_capacity():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        last_status = None
        for _ in range(10):
            resp = await client.post(
                "/api/v1/repos/analyze",
                json={"repo_url": "https://github.com/octocat/Hello-World"},
                headers=headers,
            )
            last_status = resp.status_code
        assert last_status == 429


@pytest.mark.asyncio
async def test_get_nonexistent_job_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        resp = await client.get(f"/api/v1/jobs/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 404
```

- [ ] **Step 7: Run it, verify it passes**

Run: `pytest -m integration tests/integration/test_repos_api.py -v`
Expected: PASS (requires Postgres + Redis running; does not require the worker process — jobs stay `pending`)

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Add repos/analyze and jobs API with rate limiting"
```

---

### Task 13: Hybrid search core (vector + keyword, RRF fusion)

**Files:**
- Create: `backend/app/core/search.py`
- Test: `backend/tests/unit/test_search_fusion.py`
- Test: `backend/tests/integration/test_search.py`

**Interfaces:**
- Consumes: `CodeChunk` from `app.db.models` (Task 3)
- Produces: `reciprocal_rank_fusion(*ranked_id_lists: list[UUID], k: int = 60) -> list[tuple[UUID, float]]`
- Produces: `@dataclass SearchResult(chunk_id, file_path, symbol_name, node_type, start_line, end_line, content, score)`
- Produces: `async def hybrid_search(db: AsyncSession, repo_id: UUID, query_text: str, query_embedding: list[float], limit: int = 10) -> list[SearchResult]`, consumed by Task 14's search route

- [ ] **Step 1: Write the pure-logic test**

`backend/tests/unit/test_search_fusion.py`:
```python
import uuid

from app.core.search import reciprocal_rank_fusion


def test_rrf_favors_items_ranked_high_in_both_lists():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fused = reciprocal_rank_fusion([a, b, c], [a, c, b])
    fused_ids = [item[0] for item in fused]
    assert fused_ids[0] == a


def test_rrf_includes_items_present_in_only_one_list():
    a, b = uuid.uuid4(), uuid.uuid4()
    fused = reciprocal_rank_fusion([a], [b])
    assert {item[0] for item in fused} == {a, b}


def test_rrf_empty_lists_returns_empty():
    assert reciprocal_rank_fusion([], []) == []
```

- [ ] **Step 2: Run it, verify it fails**

Run: `pytest tests/unit/test_search_fusion.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write app/core/search.py**

```python
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CodeChunk

RRF_K = 60


@dataclass
class SearchResult:
    chunk_id: UUID
    file_path: str
    symbol_name: str | None
    node_type: str
    start_line: int
    end_line: int
    content: str
    score: float


def reciprocal_rank_fusion(*ranked_id_lists: list[UUID], k: int = RRF_K) -> list[tuple[UUID, float]]:
    scores: dict[UUID, float] = {}
    for ranked_ids in ranked_id_lists:
        for rank, chunk_id in enumerate(ranked_ids, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


async def vector_search(db: AsyncSession, repo_id: UUID, query_embedding: list[float], limit: int) -> list[CodeChunk]:
    result = await db.execute(
        select(CodeChunk)
        .where(CodeChunk.repo_id == repo_id)
        .order_by(CodeChunk.embedding.cosine_distance(query_embedding))
        .limit(limit)
    )
    return list(result.scalars().all())


async def keyword_search(db: AsyncSession, repo_id: UUID, query_text: str, limit: int) -> list[CodeChunk]:
    result = await db.execute(
        select(CodeChunk)
        .where(CodeChunk.repo_id == repo_id, text("content_tsv @@ plainto_tsquery('english', :query)"))
        .params(query=query_text)
        .order_by(text("ts_rank(content_tsv, plainto_tsquery('english', :query)) DESC"))
        .limit(limit)
    )
    return list(result.scalars().all())


async def hybrid_search(
    db: AsyncSession, repo_id: UUID, query_text: str, query_embedding: list[float], limit: int = 10
) -> list[SearchResult]:
    vector_results = await vector_search(db, repo_id, query_embedding, limit=limit * 2)
    keyword_results = await keyword_search(db, repo_id, query_text, limit=limit * 2)

    chunks_by_id = {c.id: c for c in [*vector_results, *keyword_results]}
    fused = reciprocal_rank_fusion([c.id for c in vector_results], [c.id for c in keyword_results])

    results: list[SearchResult] = []
    for chunk_id, score in fused[:limit]:
        chunk = chunks_by_id[chunk_id]
        results.append(
            SearchResult(
                chunk_id=chunk.id,
                file_path=chunk.file_path,
                symbol_name=chunk.symbol_name,
                node_type=chunk.node_type.value,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                content=chunk.content,
                score=score,
            )
        )
    return results
```

- [ ] **Step 4: Run the fusion test, verify it passes**

Run: `pytest tests/unit/test_search_fusion.py -v`
Expected: PASS

- [ ] **Step 5: Write the DB-backed test**

`backend/tests/integration/test_search.py`:
```python
import uuid

import pytest

from app.core.embeddings import embed_text
from app.core.search import hybrid_search
from app.db.models import CodeChunk, NodeType, Repo, RepoStatus, User

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.mark.asyncio
async def test_hybrid_search_finds_relevant_chunk_by_keyword(db_session):
    user = User(email=f"search-{uuid.uuid4()}@example.com", hashed_password="hashed")
    db_session.add(user)
    await db_session.flush()

    repo = Repo(user_id=user.id, url="https://github.com/example/repo", name="repo", status=RepoStatus.READY)
    db_session.add(repo)
    await db_session.flush()

    target_content = "def calculate_tax(income, rate):\n    return income * rate"
    other_content = "def render_homepage():\n    return '<html></html>'"

    db_session.add_all([
        CodeChunk(
            repo_id=repo.id, file_path="tax.py", symbol_name="calculate_tax", node_type=NodeType.FUNCTION,
            start_line=1, end_line=2, content=target_content, embedding=embed_text(target_content),
        ),
        CodeChunk(
            repo_id=repo.id, file_path="views.py", symbol_name="render_homepage", node_type=NodeType.FUNCTION,
            start_line=1, end_line=2, content=other_content, embedding=embed_text(other_content),
        ),
    ])
    await db_session.flush()

    results = await hybrid_search(
        db_session, repo.id, query_text="calculate tax",
        query_embedding=embed_text("compute the tax owed"), limit=5,
    )

    assert len(results) > 0
    assert results[0].symbol_name == "calculate_tax"
```

- [ ] **Step 6: Run it, verify it passes**

Run: `pytest -m "integration and slow" tests/integration/test_search.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Add hybrid search: pgvector + full-text with RRF fusion"
```

---

### Task 14: Search API endpoint

**Files:**
- Create: `backend/app/schemas/search.py`
- Create: `backend/app/api/routes/search.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/test_search_api.py`

**Interfaces:**
- Consumes: `hybrid_search` from `app.core.search` (Task 13); `embed_text` from `app.core.embeddings` (Task 9); `get_current_user` from `app.api.deps` (Task 5); `Repo` from `app.db.models` (Task 3)
- Produces route: `POST /api/v1/search` — `{repo_id, query, limit?}` → `{results: [...]}`

- [ ] **Step 1: Write app/schemas/search.py**

```python
import uuid

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    repo_id: uuid.UUID
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=10, ge=1, le=50)


class SearchResultItem(BaseModel):
    chunk_id: uuid.UUID
    file_path: str
    symbol_name: str | None
    node_type: str
    start_line: int
    end_line: int
    content: str
    score: float


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
```

- [ ] **Step 2: Write app/api/routes/search.py**

```python
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.embeddings import embed_text
from app.core.search import hybrid_search
from app.db.models import Repo, User
from app.db.session import get_db
from app.schemas.search import SearchRequest, SearchResponse, SearchResultItem

router = APIRouter(prefix="/api/v1/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search_repo(
    payload: SearchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SearchResponse:
    repo = await db.get(Repo, payload.repo_id)
    if repo is None or repo.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo not found")

    query_embedding = embed_text(payload.query)
    results = await hybrid_search(
        db, payload.repo_id, query_text=payload.query, query_embedding=query_embedding, limit=payload.limit
    )
    return SearchResponse(
        results=[
            SearchResultItem(
                chunk_id=r.chunk_id, file_path=r.file_path, symbol_name=r.symbol_name, node_type=r.node_type,
                start_line=r.start_line, end_line=r.end_line, content=r.content, score=r.score,
            )
            for r in results
        ]
    )
```

- [ ] **Step 3: Wire the router into main.py**

Modify `backend/app/main.py`:
```python
from app.api.routes import auth, jobs, repos, search

app.include_router(auth.router)
app.include_router(repos.router)
app.include_router(jobs.router)
app.include_router(search.router)
```

- [ ] **Step 4: Write the test**

`backend/tests/integration/test_search_api.py`:
```python
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.embeddings import embed_text
from app.db.models import CodeChunk, NodeType, Repo, RepoStatus
from app.db.session import async_session_maker
from app.main import app

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.mark.asyncio
async def test_search_endpoint_returns_matching_chunk():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        email = f"searchapi-{uuid.uuid4()}@example.com"
        await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
        login_resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        me_resp = await client.get("/api/v1/auth/me", headers=headers)
        user_id = me_resp.json()["id"]

        async with async_session_maker() as db:
            repo = Repo(user_id=user_id, url="https://github.com/example/repo2", name="repo2", status=RepoStatus.READY)
            db.add(repo)
            await db.flush()

            content = "def parse_config(path):\n    return open(path).read()"
            db.add(CodeChunk(
                repo_id=repo.id, file_path="config.py", symbol_name="parse_config", node_type=NodeType.FUNCTION,
                start_line=1, end_line=2, content=content, embedding=embed_text(content),
            ))
            await db.commit()
            repo_id = str(repo.id)

        resp = await client.post(
            "/api/v1/search", json={"repo_id": repo_id, "query": "parse configuration file"}, headers=headers
        )
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) > 0
        assert results[0]["symbol_name"] == "parse_config"


@pytest.mark.asyncio
async def test_search_endpoint_rejects_other_users_repo():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        owner_email = f"owner-{uuid.uuid4()}@example.com"
        await client.post("/api/v1/auth/register", json={"email": owner_email, "password": "supersecret123"})
        owner_login = await client.post("/api/v1/auth/login", json={"email": owner_email, "password": "supersecret123"})
        owner_token = owner_login.json()["access_token"]
        owner_me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {owner_token}"})
        owner_id = owner_me.json()["id"]

        async with async_session_maker() as db:
            repo = Repo(user_id=owner_id, url="https://github.com/example/private", name="private", status=RepoStatus.READY)
            db.add(repo)
            await db.commit()
            repo_id = str(repo.id)

        other_email = f"other-{uuid.uuid4()}@example.com"
        await client.post("/api/v1/auth/register", json={"email": other_email, "password": "supersecret123"})
        other_login = await client.post("/api/v1/auth/login", json={"email": other_email, "password": "supersecret123"})
        other_token = other_login.json()["access_token"]

        resp = await client.post(
            "/api/v1/search", json={"repo_id": repo_id, "query": "anything"},
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 404
```

- [ ] **Step 5: Run it, verify it passes**

Run: `pytest -m "integration and slow" tests/integration/test_search_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add search API with per-user repo ownership check"
```

---

### Task 15: Backend Dockerfile + full docker-compose stack

**Files:**
- Create: `backend/Dockerfile`
- Create: `backend/.dockerignore`
- Modify: `docker-compose.yml`

**Interfaces:**
- Consumes: `WorkerSettings` from `app.workers.settings` (Task 11, referenced as `app.workers.settings.WorkerSettings` in the `arq` CLI command)
- Produces: running `api` service on `localhost:8000`, running `worker` service consuming the same Redis queue

- [ ] **Step 1: Write backend/.dockerignore**

```
__pycache__/
*.pyc
.pytest_cache/
.venv/
venv/
tests/
keys/*.pem
.env
```

- [ ] **Step 2: Write backend/Dockerfile**

```dockerfile
FROM python:3.12-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS runtime

COPY . .

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

- [ ] **Step 3: Extend docker-compose.yml with api and worker services**

Add to the `services:` section of the root `docker-compose.yml` (alongside the existing `postgres` and `redis` services from Task 2):
```yaml
  api:
    build:
      context: ./backend
    container_name: repo-analyzer-api
    environment:
      DATABASE_URL: postgresql+asyncpg://repoanalyzer:repoanalyzer@postgres:5432/repoanalyzer
      REDIS_URL: redis://redis:6379/0
      JWT_PRIVATE_KEY_PATH: keys/jwt_private.pem
      JWT_PUBLIC_KEY_PATH: keys/jwt_public.pem
    ports:
      - "8000:8000"
    volumes:
      - ./backend/keys:/app/keys
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  worker:
    build:
      context: ./backend
    container_name: repo-analyzer-worker
    environment:
      DATABASE_URL: postgresql+asyncpg://repoanalyzer:repoanalyzer@postgres:5432/repoanalyzer
      REDIS_URL: redis://redis:6379/0
      JWT_PRIVATE_KEY_PATH: keys/jwt_private.pem
      JWT_PUBLIC_KEY_PATH: keys/jwt_public.pem
    volumes:
      - ./backend/keys:/app/keys
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: ["arq", "app.workers.settings.WorkerSettings"]
```

- [ ] **Step 4: Build and start the full stack**

```bash
docker compose up -d --build
docker compose ps
```
Expected: `postgres`, `redis` healthy; `api`, `worker` running.

- [ ] **Step 5: Apply migrations against the containerized Postgres**

```bash
docker compose exec api alembic upgrade head
```

- [ ] **Step 6: Smoke test the full pipeline end-to-end**

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "demo@example.com", "password": "supersecret123"}'

TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "demo@example.com", "password": "supersecret123"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -X POST http://localhost:8000/api/v1/repos/analyze \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"repo_url": "https://github.com/octocat/Hello-World"}'
```
Poll `GET /api/v1/jobs/{job_id}` until `status` is `completed`, then:
```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"repo_id": "<repo_id from analyze response>", "query": "readme"}'
```
Expected: search returns results with file/line metadata.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Add backend Dockerfile and full docker-compose stack (api + worker)"
```

---

### Task 16: README

**Files:**
- Create: `README.md` (root)

- [ ] **Step 1: Write README.md**

```markdown
# Repo Analyzer — Analysis Core

Backend engine for the Autonomous AI GitHub Repository Deep Analyzer: clone a
repo, parse it with Tree-sitter, chunk it at function/class granularity,
embed chunks locally with CodeBERT, and search it via hybrid (vector +
keyword) search. No frontend in this phase — verified via API and tests.

## Setup

1. `cd backend && python -m venv .venv && source .venv/Scripts/activate`
2. `pip install -r requirements.txt`
3. `python scripts/generate_keys.py` — generates a local JWT RS256 keypair
   (gitignored; regenerate per environment)
4. `cp .env.example .env`
5. From the repo root: `docker compose up -d postgres redis`
6. `cd backend && alembic upgrade head`
7. Run the API locally: `uvicorn app.main:app --reload`
   Run the worker locally: `arq app.workers.settings.WorkerSettings`

   Or run the full containerized stack instead of steps 6-7:
   `docker compose up -d --build` then `docker compose exec api alembic upgrade head`

## Tests

- Fast unit tests (no external services): `pytest -m "not integration and not slow"`
- Integration tests (needs `docker compose up -d postgres redis`): `pytest -m integration`
- Slow tests (downloads/runs the real CodeBERT model, ~500MB first run): `pytest -m slow`
- Everything: `pytest`

## Example walkthrough

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" -d '{"email":"you@example.com","password":"supersecret123"}'

curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" -d '{"email":"you@example.com","password":"supersecret123"}'
# -> {"access_token": "..."}

curl -X POST http://localhost:8000/api/v1/repos/analyze \
  -H "Content-Type: application/json" -H "Authorization: Bearer <token>" \
  -d '{"repo_url": "https://github.com/octocat/Hello-World"}'
# -> {"repo_id": "...", "job_id": "..."}

curl http://localhost:8000/api/v1/jobs/<job_id> -H "Authorization: Bearer <token>"
# poll until "status": "completed"

curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" -H "Authorization: Bearer <token>" \
  -d '{"repo_id": "<repo_id>", "query": "readme"}'
```

## Non-goals in this phase

No frontend, no LangGraph multi-agent workflow, no org/RBAC beyond
one-workspace-per-user, no load testing at scale, no Kubernetes deployment.
See `docs/superpowers/specs/2026-08-16-analysis-core-design.md` for the full
design and the list of future sub-projects.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Add README with setup, testing, and API walkthrough"
```
