# Multi-Agent Chat Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a conversational agent (LangGraph-based, single agent with tool access) that answers questions about an analyzed repo by searching its code and citing exact file/line references, streamed to clients over SSE — plus the file-tree/file-content API the frontend (sub-project 2B) needs.

**Architecture:** A pluggable `LLMClient` interface (real Anthropic/OpenAI implementations plus a deterministic `FakeLLMClient` for tests) is driven by a LangGraph `StateGraph` implementing an assistant↔tools ReAct loop. The only tool is `search_code`, wrapping the existing `hybrid_search`. Conversations and messages persist to Postgres; the chat endpoint streams `LLMEvent`s out as Server-Sent Events and saves the final exchange once the stream completes.

**Tech Stack:** LangGraph (StateGraph, custom stream mode), Anthropic + OpenAI Python SDKs (pluggable), FastAPI `StreamingResponse` for SSE, SQLAlchemy 2.0 async (new tables), existing `hybrid_search`/`embed_text` (unchanged).

**Spec:** `docs/superpowers/specs/2026-08-16-agent-engine-design.md`

## Global Constraints

- No live LLM API calls in any automated test — every test uses `FakeLLMClient`; a real run is a manual smoke-test step once an API key exists (not automated here)
- No live GitHub network calls in automated tests (inherited from sub-project 1 — still applies to ingestion tests)
- SSE stream errors (LLM/tool failures) surface as a clean `error` event, never a raw 500 mid-stream
- Every new per-repo/per-conversation endpoint enforces ownership via 404 (never 403 — no existence leak), matching the existing pattern in `search.py`/`jobs.py`
- Re-analyzing a repo must not duplicate `files` rows, mirroring the existing `CodeChunk` replace-on-reanalysis behavior — same transaction, same atomicity guarantee
- No placeholders — every file created is real, runnable code
- The agent loop is a genuine LangGraph `StateGraph` (not a hand-rolled loop dressed up as one) — see Task 7 for a documented fallback if the installed LangGraph version lacks the specific streaming API this design uses

---

### Task 1: Database models + migration (files, conversations, messages)

**Files:**
- Modify: `backend/app/db/models.py:41-51` (User — add `conversations` relationship), `backend/app/db/models.py:66-84` (Repo — add `files`/`conversations` relationships)
- Modify: `backend/app/db/models.py` (append new `File`, `MessageRole`, `Conversation`, `Message` classes at the end of the file, after `CodeChunk`)
- Create: `backend/alembic/versions/0002_agent_engine_schema.py` (via autogenerate)
- Test: `backend/tests/integration/test_agent_models.py`

**Interfaces:**
- Produces: `File(id, repo_id, path, content, created_at)` with `UniqueConstraint(repo_id, path)`
- Produces: `MessageRole` enum (`USER`, `ASSISTANT`), `Conversation(id, repo_id, user_id, title, created_at)`, `Message(id, conversation_id, role, content, created_at)` — consumed by Tasks 2 (files), 8 (conversations API), 9 (chat endpoint) by these exact names

- [ ] **Step 1: Modify the `User` class**

In `backend/app/db/models.py`, find this line (currently line 50):
```python
    repos: Mapped[list["Repo"]] = relationship(back_populates="user", cascade="all, delete-orphan")
```
Add immediately after it:
```python
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user", cascade="all, delete-orphan")
```

- [ ] **Step 2: Modify the `Repo` class**

Find this line (currently line 82):
```python
    chunks: Mapped[list["CodeChunk"]] = relationship(back_populates="repo", cascade="all, delete-orphan")
```
Add immediately after it:
```python
    files: Mapped[list["File"]] = relationship(back_populates="repo", cascade="all, delete-orphan")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="repo", cascade="all, delete-orphan")
```

- [ ] **Step 3: Append the new model classes**

At the end of `backend/app/db/models.py` (after the `CodeChunk` class), add:
```python
class File(Base):
    __tablename__ = "files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    repo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), nullable=False)
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    repo: Mapped["Repo"] = relationship(back_populates="files")

    __table_args__ = (
        UniqueConstraint("repo_id", "path", name="uq_files_repo_id_path"),
        Index("ix_files_repo_id", "repo_id"),
    )


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    repo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    repo: Mapped["Repo"] = relationship(back_populates="conversations")
    user: Mapped["User"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at"
    )

    __table_args__ = (
        Index("ix_conversations_repo_id", "repo_id"),
        Index("ix_conversations_user_id", "user_id"),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, name="message_role", values_callable=lambda e: [m.value for m in e]), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

    __table_args__ = (Index("ix_messages_conversation_id", "conversation_id"),)
```

- [ ] **Step 4: Generate and apply the migration**

From `backend/` (venv activated, `docker compose up -d postgres redis` running from the repo root):
```bash
alembic revision --autogenerate -m "add files, conversations, messages"
```
Rename the generated file under `backend/alembic/versions/` to `0002_agent_engine_schema.py`. Open it and confirm it creates the `files`, `conversations`, and `messages` tables with the columns/constraints above — no manual edits should be needed this time (unlike migration `0001`, there's no vector extension or custom index to hand-add). If autogenerate produces something that doesn't match, fix the migration file to match the model definitions above before proceeding.

Apply it:
```bash
alembic upgrade head
```
Verify: `docker compose exec postgres psql -U repoanalyzer -d repoanalyzer -c "\dt"` (from the repo root) shows `files`, `conversations`, `messages` alongside the existing tables.

- [ ] **Step 5: Write the test**

`backend/tests/integration/test_agent_models.py`:
```python
import uuid

import pytest
from sqlalchemy import select

from app.db.models import Conversation, File, Message, MessageRole, Repo, RepoStatus, User

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_create_and_query_file(db_session):
    user = User(email=f"test-{uuid.uuid4()}@example.com", hashed_password="hashed")
    db_session.add(user)
    await db_session.flush()

    repo = Repo(user_id=user.id, url="https://github.com/example/repo", name="repo", status=RepoStatus.READY)
    db_session.add(repo)
    await db_session.flush()

    file = File(repo_id=repo.id, path="src/main.py", content="def main(): pass")
    db_session.add(file)
    await db_session.flush()

    result = await db_session.execute(select(File).where(File.repo_id == repo.id))
    fetched = result.scalar_one()
    assert fetched.path == "src/main.py"
    assert fetched.content == "def main(): pass"


@pytest.mark.asyncio
async def test_conversation_and_messages_roundtrip(db_session):
    user = User(email=f"test-{uuid.uuid4()}@example.com", hashed_password="hashed")
    db_session.add(user)
    await db_session.flush()

    repo = Repo(user_id=user.id, url="https://github.com/example/repo2", name="repo2", status=RepoStatus.READY)
    db_session.add(repo)
    await db_session.flush()

    conversation = Conversation(repo_id=repo.id, user_id=user.id, title="First chat")
    db_session.add(conversation)
    await db_session.flush()

    db_session.add(Message(conversation_id=conversation.id, role=MessageRole.USER, content="What does main do?"))
    db_session.add(Message(conversation_id=conversation.id, role=MessageRole.ASSISTANT, content="It calls pass."))
    await db_session.flush()

    result = await db_session.execute(select(Conversation).where(Conversation.id == conversation.id))
    fetched = result.scalar_one()
    await db_session.refresh(fetched, attribute_names=["messages"])
    assert len(fetched.messages) == 2
    assert fetched.messages[0].role == MessageRole.USER


@pytest.mark.asyncio
async def test_files_unique_constraint_per_repo_and_path(db_session):
    user = User(email=f"test-{uuid.uuid4()}@example.com", hashed_password="hashed")
    db_session.add(user)
    await db_session.flush()

    repo = Repo(user_id=user.id, url="https://github.com/example/repo3", name="repo3", status=RepoStatus.READY)
    db_session.add(repo)
    await db_session.flush()

    db_session.add(File(repo_id=repo.id, path="a.py", content="one"))
    await db_session.flush()
    db_session.add(File(repo_id=repo.id, path="a.py", content="two"))

    with pytest.raises(Exception):
        await db_session.flush()
```

- [ ] **Step 6: Run it, verify it passes**

Run: `pytest -m integration tests/integration/test_agent_models.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Add files, conversations, messages models and migration"
```

---

### Task 2: Ingestion extension — persist full file content

**Files:**
- Modify: `backend/app/core/ingestion.py` (full rewrite — see below)
- Modify: `backend/app/workers/tasks.py` (wire file storage into `analyze_repo`)
- Modify: `backend/tests/unit/test_ingestion.py` (update call sites for the new return type)
- Test: `backend/tests/integration/test_worker_tasks.py` (add a re-analysis-doesn't-duplicate-files test, mirroring the existing chunk one)

**Interfaces:**
- Consumes: `Chunk`, `chunk_file` from `app.core.chunker` (unchanged); `File` from `app.db.models` (Task 1)
- Produces: `WalkedFile(path: str, content: str)`, `WalkResult(chunks: list[Chunk], files: list[WalkedFile], files_processed: int, files_skipped: int)` — **replaces** `walk_and_chunk`'s old `tuple[list[Chunk], int, int]` return type; every caller must be updated in this task
- Produces: `IngestionResult` gains a `files: list[WalkedFile]` field

- [ ] **Step 1: Rewrite `backend/app/core/ingestion.py`**

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
class WalkedFile:
    path: str
    content: str


@dataclass
class WalkResult:
    chunks: list[Chunk]
    files: list[WalkedFile]
    files_processed: int
    files_skipped: int


@dataclass
class IngestionResult:
    chunks: list[ChunkWithEmbedding]
    files: list[WalkedFile]
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


def walk_and_chunk(root_dir: Path, max_files: int) -> WalkResult:
    all_chunks: list[Chunk] = []
    all_files: list[WalkedFile] = []
    files_processed = 0
    files_skipped = 0
    resolved_root = root_dir.resolve()

    for path in sorted(root_dir.rglob("*")):
        if path.is_dir():
            continue
        if any(_should_skip_dir(part) for part in path.relative_to(root_dir).parts[:-1]):
            continue
        if files_processed + files_skipped >= max_files:
            break

        if path.is_symlink():
            files_skipped += 1
            continue

        try:
            if not path.resolve().is_relative_to(resolved_root):
                files_skipped += 1
                continue
        except OSError:
            files_skipped += 1
            continue

        try:
            if path.stat().st_size > MAX_FILE_SIZE_BYTES:
                files_skipped += 1
                continue
        except OSError:
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
            all_files.append(WalkedFile(path=relative_path, content=source))
            files_processed += 1
        except Exception:
            files_skipped += 1
            continue

    return WalkResult(chunks=all_chunks, files=all_files, files_processed=files_processed, files_skipped=files_skipped)


def embed_chunks(chunks: list[Chunk], batch_size: int = 8) -> list[ChunkWithEmbedding]:
    if not chunks:
        return []
    embeddings = embed_texts([c.content for c in chunks], batch_size=batch_size)
    return [ChunkWithEmbedding(chunk=c, embedding=e) for c, e in zip(chunks, embeddings)]


def ingest_local_directory(root_dir: Path, max_files: int) -> IngestionResult:
    walk_result = walk_and_chunk(root_dir, max_files)
    embedded = embed_chunks(walk_result.chunks)
    return IngestionResult(
        chunks=embedded,
        files=walk_result.files,
        files_processed=walk_result.files_processed,
        files_skipped=walk_result.files_skipped,
    )
```

- [ ] **Step 2: Update `backend/app/workers/tasks.py`**

Replace this line:
```python
                chunks, _processed, skipped = walk_and_chunk(clone_path, max_files=settings.max_files_per_repo)
```
with:
```python
                walk_result = walk_and_chunk(clone_path, max_files=settings.max_files_per_repo)
```

Replace this line:
```python
                embedded = embed_chunks(chunks)
```
with:
```python
                embedded = embed_chunks(walk_result.chunks)
```

Immediately after the existing `await db.execute(delete(CodeChunk).where(CodeChunk.repo_id == repo.id))` line, add the equivalent delete for `File`:
```python
                await db.execute(delete(File).where(File.repo_id == repo.id))
```

After the existing `for item in embedded: db.add(CodeChunk(...))` loop, add a loop storing the walked files:
```python
                for walked_file in walk_result.files:
                    db.add(File(repo_id=repo.id, path=walked_file.path, content=walked_file.content))
```

Replace this line:
```python
                job.skipped_files = skipped
```
with:
```python
                job.skipped_files = walk_result.files_skipped
```

Update the imports at the top of the file — change:
```python
from app.db.models import CodeChunk, Job, JobStatus, NodeType, Repo, RepoStatus
```
to:
```python
from app.db.models import CodeChunk, File, Job, JobStatus, NodeType, Repo, RepoStatus
```

- [ ] **Step 3: Update `backend/tests/unit/test_ingestion.py` call sites**

`walk_and_chunk` now returns a `WalkResult` dataclass instead of a 3-tuple. Update every test that unpacks it. Replace:
```python
def test_walk_and_chunk_processes_all_fixture_files():
    chunks, processed, skipped = walk_and_chunk(FIXTURE_DIR, max_files=100)
    assert processed == 3
    assert skipped == 0
    symbol_names = {c.symbol_name for c in chunks if c.symbol_name}
```
with:
```python
def test_walk_and_chunk_processes_all_fixture_files():
    result = walk_and_chunk(FIXTURE_DIR, max_files=100)
    assert result.files_processed == 3
    assert result.files_skipped == 0
    assert len(result.files) == 3
    symbol_names = {c.symbol_name for c in result.chunks if c.symbol_name}
```
(keep the three `assert "..." in symbol_names` lines unchanged below it).

Replace:
```python
def test_walk_and_chunk_respects_max_files():
    chunks, processed, skipped = walk_and_chunk(FIXTURE_DIR, max_files=1)
    assert processed == 1
```
with:
```python
def test_walk_and_chunk_respects_max_files():
    result = walk_and_chunk(FIXTURE_DIR, max_files=1)
    assert result.files_processed == 1
```

In `test_walk_and_chunk_skips_symlink_pointing_outside_root`, replace:
```python
    chunks, processed, skipped = walk_and_chunk(repo_dir, max_files=100)

    # Only the three legitimate fixture files should be processed; the
    # symlink must be skipped, not read, not chunked.
    assert processed == 3
    assert skipped == 1
    assert not any("SUPER_SECRET_KEY_MATERIAL" in c.content for c in chunks)
    assert not any(c.file_path == "sneaky_link.py" for c in chunks)
```
with:
```python
    result = walk_and_chunk(repo_dir, max_files=100)

    # Only the three legitimate fixture files should be processed; the
    # symlink must be skipped, not read, not chunked.
    assert result.files_processed == 3
    assert result.files_skipped == 1
    assert not any("SUPER_SECRET_KEY_MATERIAL" in c.content for c in result.chunks)
    assert not any(c.file_path == "sneaky_link.py" for c in result.chunks)
    assert not any("SUPER_SECRET_KEY_MATERIAL" in f.content for f in result.files)
```

In `test_walk_and_chunk_skips_file_that_resolves_outside_root`, replace:
```python
    chunks, processed, skipped = walk_and_chunk(repo_dir, max_files=100)

    assert not any("outside content" in c.content for c in chunks)
    assert processed == 0
```
with:
```python
    result = walk_and_chunk(repo_dir, max_files=100)

    assert not any("outside content" in c.content for c in result.chunks)
    assert result.files_processed == 0
```

In `test_walk_and_chunk_skips_symlink_via_monkeypatch`, replace:
```python
    chunks, processed, skipped = walk_and_chunk(repo_dir, max_files=100)

    assert not any(c.file_path == "main.py" for c in chunks)
    assert processed == 2
    assert skipped == 1
```
with:
```python
    result = walk_and_chunk(repo_dir, max_files=100)

    assert not any(c.file_path == "main.py" for c in result.chunks)
    assert result.files_processed == 2
    assert result.files_skipped == 1
    assert not any(f.path == "main.py" for f in result.files)
```

In `test_ingest_local_directory_produces_embeddings`, add a new assertion after the existing ones:
```python
    assert len(result.files) == 3
```

- [ ] **Step 4: Run the unit tests**

Run: `pytest tests/unit/test_ingestion.py -v`
Expected: all PASS (2 symlink tests SKIPPED as before, same as sub-project 1's known environment limitation)

- [ ] **Step 5: Add the re-analysis-doesn't-duplicate-files test**

In `backend/tests/integration/test_worker_tasks.py`, find `test_analyze_repo_task_reanalysis_does_not_duplicate_chunks` and add a sibling test right after it:
```python
@pytest.mark.asyncio
async def test_analyze_repo_task_reanalysis_does_not_duplicate_files(local_git_repo_url):
    from app.db.models import File

    async with async_session_maker() as db:
        user = User(email=f"worker-{uuid.uuid4()}@example.com", hashed_password="hashed")
        db.add(user)
        await db.flush()

        repo = Repo(user_id=user.id, url=local_git_repo_url, name="local-repo", status=RepoStatus.PENDING)
        db.add(repo)
        await db.flush()

        job1 = Job(repo_id=repo.id, status=JobStatus.PENDING)
        db.add(job1)
        await db.commit()
        job1_id = str(job1.id)
        repo_id = repo.id
        user_id = user.id

    await analyze_repo({}, job1_id)

    async with async_session_maker() as db:
        result = await db.execute(select(File).where(File.repo_id == repo_id))
        count_after_first = len(result.scalars().all())
        assert count_after_first > 0

        job2 = Job(repo_id=repo_id, status=JobStatus.PENDING)
        db.add(job2)
        await db.commit()
        job2_id = str(job2.id)

    await analyze_repo({}, job2_id)

    async with async_session_maker() as db:
        result = await db.execute(select(File).where(File.repo_id == repo_id))
        files_after_second = result.scalars().all()
        assert len(files_after_second) == count_after_first

        for f in files_after_second:
            await db.delete(f)
        result = await db.execute(select(Job).where(Job.repo_id == repo_id))
        for job in result.scalars().all():
            await db.delete(job)
        refreshed_repo = await db.get(Repo, repo_id)
        await db.delete(refreshed_repo)
        refreshed_user = await db.get(User, user_id)
        await db.delete(refreshed_user)
        await db.commit()
```
(This mirrors the existing `..._does_not_duplicate_chunks` test's fixture/cleanup pattern in the same file — check that file's imports already cover `select`, `async_session_maker`, `User`, `Repo`, `RepoStatus`, `Job`, `JobStatus`, `analyze_repo`, `uuid`, `pytest`, `local_git_repo_url`; only `File` needs a local import as shown since it's new to this test file.)

- [ ] **Step 6: Run it, verify it passes**

Run: `pytest -m "integration and slow" tests/integration/test_worker_tasks.py -v`
Expected: PASS (requires Postgres+Redis running; uses real embeddings, hence `slow`)

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Store full file content during ingestion; replace on re-analysis"
```

---

### Task 3: Files API (tree listing + file content)

**Files:**
- Modify: `backend/app/api/deps.py` (add `get_owned_repo` shared helper)
- Create: `backend/app/schemas/files.py`
- Create: `backend/app/api/routes/files.py`
- Modify: `backend/app/main.py` (wire the new router)
- Test: `backend/tests/integration/test_files_api.py`

**Interfaces:**
- Produces: `async def get_owned_repo(db: AsyncSession, repo_id: UUID, user: User) -> Repo` in `app.api.deps` — raises 404 if not found/not owned; consumed by Task 8 (and by this task's own routes)
- Produces routes: `GET /api/v1/repos/{repo_id}/files` (tree), `GET /api/v1/repos/{repo_id}/files/content?path=...`

- [ ] **Step 1: Add `get_owned_repo` to `backend/app/api/deps.py`**

Add these imports to the top of the file (alongside the existing ones):
```python
from uuid import UUID

from app.db.models import Repo
```
Add this function at the end of the file:
```python
async def get_owned_repo(db: AsyncSession, repo_id: UUID, user: User) -> Repo:
    repo = await db.get(Repo, repo_id)
    if repo is None or repo.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo not found")
    return repo
```

- [ ] **Step 2: Write `backend/app/schemas/files.py`**

```python
from pydantic import BaseModel


class FileTreeEntry(BaseModel):
    name: str
    path: str
    type: str  # "file" | "directory"
    children: list["FileTreeEntry"] | None = None


FileTreeEntry.model_rebuild()


class FileTreeResponse(BaseModel):
    entries: list[FileTreeEntry]


class FileContentResponse(BaseModel):
    path: str
    content: str
```

- [ ] **Step 3: Write `backend/app/api/routes/files.py`**

```python
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_owned_repo
from app.db.models import File, User
from app.db.session import get_db
from app.schemas.files import FileContentResponse, FileTreeEntry, FileTreeResponse

router = APIRouter(prefix="/api/v1/repos", tags=["files"])


def _build_tree(paths: list[str]) -> list[FileTreeEntry]:
    root: dict = {}
    for path in paths:
        parts = path.split("/")
        node = root
        for i, part in enumerate(parts):
            is_leaf = i == len(parts) - 1
            if part not in node:
                node[part] = {"__type__": "file" if is_leaf else "directory", "__children__": {}}
            node = node[part]["__children__"]

    def to_entries(tree: dict, prefix: str) -> list[FileTreeEntry]:
        entries = []
        for name in sorted(tree.keys()):
            info = tree[name]
            full_path = f"{prefix}/{name}" if prefix else name
            if info["__type__"] == "directory":
                entries.append(
                    FileTreeEntry(
                        name=name, path=full_path, type="directory",
                        children=to_entries(info["__children__"], full_path),
                    )
                )
            else:
                entries.append(FileTreeEntry(name=name, path=full_path, type="file", children=None))
        return entries

    return to_entries(root, "")


@router.get("/{repo_id}/files", response_model=FileTreeResponse)
async def get_file_tree(
    repo_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileTreeResponse:
    await get_owned_repo(db, repo_id, current_user)
    result = await db.execute(select(File.path).where(File.repo_id == repo_id))
    paths = sorted(result.scalars().all())
    return FileTreeResponse(entries=_build_tree(paths))


@router.get("/{repo_id}/files/content", response_model=FileContentResponse)
async def get_file_content(
    repo_id: UUID,
    path: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileContentResponse:
    await get_owned_repo(db, repo_id, current_user)
    result = await db.execute(select(File).where(File.repo_id == repo_id, File.path == path))
    file = result.scalar_one_or_none()
    if file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return FileContentResponse(path=file.path, content=file.content)
```

- [ ] **Step 4: Wire the router into main.py**

In `backend/app/main.py`, replace:
```python
from app.api.routes import auth, jobs, repos, search
```
with:
```python
from app.api.routes import auth, files, jobs, repos, search
```
and replace:
```python
app.include_router(auth.router)
app.include_router(repos.router)
app.include_router(jobs.router)
app.include_router(search.router)
```
with:
```python
app.include_router(auth.router)
app.include_router(repos.router)
app.include_router(jobs.router)
app.include_router(search.router)
app.include_router(files.router)
```

- [ ] **Step 5: Write the test**

`backend/tests/integration/test_files_api.py`:
```python
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import File, Repo, RepoStatus
from app.db.session import async_session_maker
from app.main import app

pytestmark = pytest.mark.integration


async def _register_and_login(client: AsyncClient) -> str:
    email = f"files-{uuid.uuid4()}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
    login_resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
    return login_resp.json()["access_token"]


@pytest.mark.asyncio
async def test_file_tree_and_content_flow():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}

        me_resp = await client.get("/api/v1/auth/me", headers=headers)
        user_id = me_resp.json()["id"]

        async with async_session_maker() as db:
            repo = Repo(user_id=user_id, url="https://github.com/example/filesrepo", name="filesrepo", status=RepoStatus.READY)
            db.add(repo)
            await db.flush()
            db.add(File(repo_id=repo.id, path="src/main.py", content="def main(): pass"))
            db.add(File(repo_id=repo.id, path="src/utils/helpers.py", content="def helper(): pass"))
            db.add(File(repo_id=repo.id, path="README.md", content="# Hello"))
            await db.commit()
            repo_id = str(repo.id)

        tree_resp = await client.get(f"/api/v1/repos/{repo_id}/files", headers=headers)
        assert tree_resp.status_code == 200
        entries = tree_resp.json()["entries"]
        names_at_root = {e["name"] for e in entries}
        assert names_at_root == {"src", "README.md"}
        src_entry = next(e for e in entries if e["name"] == "src")
        assert src_entry["type"] == "directory"
        assert {c["name"] for c in src_entry["children"]} == {"main.py", "utils"}

        content_resp = await client.get(
            f"/api/v1/repos/{repo_id}/files/content", params={"path": "src/main.py"}, headers=headers
        )
        assert content_resp.status_code == 200
        assert content_resp.json()["content"] == "def main(): pass"

        missing_resp = await client.get(
            f"/api/v1/repos/{repo_id}/files/content", params={"path": "nope.py"}, headers=headers
        )
        assert missing_resp.status_code == 404


@pytest.mark.asyncio
async def test_files_endpoints_reject_other_users_repo():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        owner_token = await _register_and_login(client)
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        owner_me = await client.get("/api/v1/auth/me", headers=owner_headers)
        owner_id = owner_me.json()["id"]

        async with async_session_maker() as db:
            repo = Repo(user_id=owner_id, url="https://github.com/example/privatefiles", name="privatefiles", status=RepoStatus.READY)
            db.add(repo)
            await db.commit()
            repo_id = str(repo.id)

        other_token = await _register_and_login(client)
        other_headers = {"Authorization": f"Bearer {other_token}"}

        tree_resp = await client.get(f"/api/v1/repos/{repo_id}/files", headers=other_headers)
        assert tree_resp.status_code == 404

        content_resp = await client.get(
            f"/api/v1/repos/{repo_id}/files/content", params={"path": "anything.py"}, headers=other_headers
        )
        assert content_resp.status_code == 404
```

- [ ] **Step 6: Run it, verify it passes**

Run: `pytest -m integration tests/integration/test_files_api.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Add file tree and file content API"
```

---

### Task 4: LLM client core (protocol, types, FakeLLMClient)

**Files:**
- Create: `backend/app/core/llm.py`
- Test: `backend/tests/unit/test_llm_fake_client.py`

**Interfaces:**
- Produces: `ToolSpec(name, description, parameters)`, `ToolCall(id, name, arguments)`, `Message(role, content, tool_calls, tool_call_id)`, `LLMEvent(type, token, tool_calls, tool_result_text, message, error)`, `LLMClient` (Protocol), `FakeLLMClient`, `ScriptedTurn(tool_calls, text)` — consumed by Task 5 (real clients implement the same `LLMClient` protocol), Task 6 (tools reference `ToolSpec`), Task 7 (agent loop consumes `LLMClient`/`Message`/`LLMEvent`), Task 9 (chat route constructs `Message`)

- [ ] **Step 1: Write the failing test**

`backend/tests/unit/test_llm_fake_client.py`:
```python
import pytest

from app.core.llm import FakeLLMClient, Message, ScriptedTurn, ToolCall, ToolSpec


@pytest.mark.asyncio
async def test_fake_client_streams_tokens_then_message_done():
    client = FakeLLMClient(turns=[ScriptedTurn(text="Hello world")])
    events = [
        event
        async for event in client.stream_chat(
            messages=[Message(role="user", content="hi")], tools=[], system_prompt="sys"
        )
    ]

    token_events = [e for e in events if e.type == "token"]
    assert "".join(e.token for e in token_events) == "Hello world "
    assert events[-1].type == "message_done"
    assert events[-1].message.content == "Hello world"


@pytest.mark.asyncio
async def test_fake_client_yields_tool_call_turn():
    tool_call = ToolCall(id="call_1", name="search_code", arguments={"query": "auth logic"})
    client = FakeLLMClient(turns=[ScriptedTurn(tool_calls=[tool_call])])

    events = [
        event
        async for event in client.stream_chat(messages=[Message(role="user", content="hi")], tools=[], system_prompt="sys")
    ]

    assert len(events) == 1
    assert events[0].type == "tool_call"
    assert events[0].tool_calls == [tool_call]


@pytest.mark.asyncio
async def test_fake_client_consumes_turns_in_order():
    client = FakeLLMClient(turns=[ScriptedTurn(text="first"), ScriptedTurn(text="second")])

    first_events = [e async for e in client.stream_chat(messages=[], tools=[], system_prompt="sys")]
    second_events = [e async for e in client.stream_chat(messages=[], tools=[], system_prompt="sys")]

    assert first_events[-1].message.content == "first"
    assert second_events[-1].message.content == "second"


@pytest.mark.asyncio
async def test_fake_client_raises_when_turns_exhausted():
    client = FakeLLMClient(turns=[])
    with pytest.raises(RuntimeError):
        async for _ in client.stream_chat(messages=[], tools=[], system_prompt="sys"):
            pass


def test_tool_spec_is_a_plain_dataclass():
    spec = ToolSpec(name="search_code", description="desc", parameters={"type": "object"})
    assert spec.name == "search_code"
```

- [ ] **Step 2: Run it, verify it fails**

Run: `pytest tests/unit/test_llm_fake_client.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.core.llm'`)

- [ ] **Step 3: Write `backend/app/core/llm.py`**

```python
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Message:
    role: Literal["user", "assistant", "tool"]
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None


@dataclass
class LLMEvent:
    type: Literal["token", "tool_call", "tool_result", "message_done", "error"]
    token: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_result_text: str | None = None
    message: Message | None = None
    error: str | None = None


class LLMClient(Protocol):
    def stream_chat(
        self, messages: list[Message], tools: list[ToolSpec], system_prompt: str
    ) -> AsyncIterator[LLMEvent]: ...


@dataclass
class ScriptedTurn:
    tool_calls: list[ToolCall] | None = None
    text: str | None = None


class FakeLLMClient:
    """Deterministic LLMClient for tests. Each call to stream_chat() consumes
    exactly one scripted turn, in order. Never makes a network call."""

    def __init__(self, turns: list[ScriptedTurn]):
        self._turns = list(turns)

    async def stream_chat(
        self, messages: list[Message], tools: list[ToolSpec], system_prompt: str
    ) -> AsyncIterator[LLMEvent]:
        if not self._turns:
            raise RuntimeError("FakeLLMClient ran out of scripted turns")
        turn = self._turns.pop(0)

        if turn.tool_calls:
            yield LLMEvent(type="tool_call", tool_calls=turn.tool_calls)
            return

        text = turn.text or ""
        for word in text.split(" "):
            yield LLMEvent(type="token", token=word + " ")
        yield LLMEvent(type="message_done", message=Message(role="assistant", content=text))
```

- [ ] **Step 4: Run it, verify it passes**

Run: `pytest tests/unit/test_llm_fake_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add LLM client protocol, message types, and FakeLLMClient"
```

---

### Task 5: Real LLM provider clients (Anthropic, OpenAI) + factory

**Files:**
- Create: `backend/app/core/llm_providers.py`
- Modify: `backend/app/config.py` (add LLM settings)
- Modify: `backend/requirements.txt` (add `anthropic`, `openai`)
- Modify: `backend/.env.example` (document the new env vars)
- Test: `backend/tests/unit/test_llm_providers.py` (message-conversion helpers only — no network calls, no real API key needed)

**Interfaces:**
- Consumes: `LLMEvent`, `Message`, `ToolCall`, `ToolSpec` from `app.core.llm` (Task 4)
- Produces: `AnthropicClient`, `OpenAIClient` (both conform to the `LLMClient` protocol), `get_llm_client() -> LLMClient` factory — consumed by Task 9 (chat endpoint)

- [ ] **Step 1: Add settings**

In `backend/app/config.py`, add these fields to the `Settings` class, after the existing `rate_limit_bucket_capacity` line:
```python
    llm_provider: str = "anthropic"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-5-20250929"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"
```

- [ ] **Step 2: Add dependencies**

In `backend/requirements.txt`, add these two lines (anywhere among the existing dependencies, e.g. after `httpx==0.27.2`):
```
anthropic==0.39.0
openai==1.54.0
```
Install: `pip install -r requirements.txt` (from `backend/`, venv activated).

- [ ] **Step 3: Document the env vars**

In `backend/.env.example`, add:
```
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-5-20250929
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o
```

- [ ] **Step 4: Write `backend/app/core/llm_providers.py`**

```python
import json
from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from app.config import get_settings
from app.core.llm import LLMEvent, Message, ToolCall, ToolSpec

settings = get_settings()


def _to_anthropic_messages(messages: list[Message]) -> list[dict]:
    result: list[dict] = []
    for msg in messages:
        if msg.role == "user":
            result.append({"role": "user", "content": msg.content})
        elif msg.role == "assistant":
            if msg.tool_calls:
                content: list[dict] = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                content.extend(
                    {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments}
                    for tc in msg.tool_calls
                )
                result.append({"role": "assistant", "content": content})
            else:
                result.append({"role": "assistant", "content": msg.content})
        elif msg.role == "tool":
            result.append({
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": msg.tool_call_id, "content": msg.content}],
            })
    return result


class AnthropicClient:
    def __init__(self, api_key: str, model: str):
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def stream_chat(
        self, messages: list[Message], tools: list[ToolSpec], system_prompt: str
    ) -> AsyncIterator[LLMEvent]:
        anthropic_tools = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools
        ]

        try:
            async with self._client.messages.stream(
                model=self._model,
                max_tokens=4096,
                system=system_prompt,
                messages=_to_anthropic_messages(messages),
                tools=anthropic_tools,
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        yield LLMEvent(type="token", token=event.delta.text)

                final_message = await stream.get_final_message()
                tool_calls = [
                    ToolCall(id=block.id, name=block.name, arguments=block.input)
                    for block in final_message.content
                    if block.type == "tool_use"
                ]
                if tool_calls:
                    yield LLMEvent(type="tool_call", tool_calls=tool_calls)
                else:
                    text = "".join(block.text for block in final_message.content if block.type == "text")
                    yield LLMEvent(type="message_done", message=Message(role="assistant", content=text))
        except Exception as exc:
            yield LLMEvent(type="error", error=str(exc))


def _to_openai_messages(messages: list[Message]) -> list[dict]:
    result: list[dict] = []
    for msg in messages:
        if msg.role == "user":
            result.append({"role": "user", "content": msg.content})
        elif msg.role == "assistant":
            if msg.tool_calls:
                result.append({
                    "role": "assistant",
                    "content": msg.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                        }
                        for tc in msg.tool_calls
                    ],
                })
            else:
                result.append({"role": "assistant", "content": msg.content})
        elif msg.role == "tool":
            result.append({"role": "tool", "tool_call_id": msg.tool_call_id, "content": msg.content})
    return result


class OpenAIClient:
    def __init__(self, api_key: str, model: str):
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def stream_chat(
        self, messages: list[Message], tools: list[ToolSpec], system_prompt: str
    ) -> AsyncIterator[LLMEvent]:
        openai_messages = [{"role": "system", "content": system_prompt}, *_to_openai_messages(messages)]
        openai_tools = [
            {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
            for t in tools
        ]

        try:
            stream = await self._client.chat.completions.create(
                model=self._model, messages=openai_messages, tools=openai_tools, stream=True,
            )

            content_parts: list[str] = []
            tool_call_accumulator: dict[int, dict] = {}

            async for chunk in stream:
                delta = chunk.choices[0].delta

                if delta.content:
                    content_parts.append(delta.content)
                    yield LLMEvent(type="token", token=delta.content)

                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        entry = tool_call_accumulator.setdefault(tc_delta.index, {"id": "", "name": "", "arguments": ""})
                        if tc_delta.id:
                            entry["id"] = tc_delta.id
                        if tc_delta.function and tc_delta.function.name:
                            entry["name"] = tc_delta.function.name
                        if tc_delta.function and tc_delta.function.arguments:
                            entry["arguments"] += tc_delta.function.arguments

            if tool_call_accumulator:
                tool_calls = [
                    ToolCall(id=entry["id"], name=entry["name"], arguments=json.loads(entry["arguments"] or "{}"))
                    for entry in tool_call_accumulator.values()
                ]
                yield LLMEvent(type="tool_call", tool_calls=tool_calls)
            else:
                yield LLMEvent(type="message_done", message=Message(role="assistant", content="".join(content_parts)))
        except Exception as exc:
            yield LLMEvent(type="error", error=str(exc))


def get_llm_client():
    current_settings = get_settings()
    if current_settings.llm_provider == "openai":
        if not current_settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured but LLM_PROVIDER=openai")
        return OpenAIClient(api_key=current_settings.openai_api_key, model=current_settings.openai_model)
    if not current_settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured but LLM_PROVIDER=anthropic")
    return AnthropicClient(api_key=current_settings.anthropic_api_key, model=current_settings.anthropic_model)
```

**Known limitation, not a defect to fix here:** neither `AnthropicClient` nor `OpenAIClient` can be exercised against a real API in this environment — no key exists yet (see plan Global Constraints and the spec's testing section). Task 6's test below covers only the pure message-conversion helper functions, which need no network access. A real end-to-end run against one of these providers is a manual step documented in Task 10's README update, to be performed once a key is added.

- [ ] **Step 5: Write the test**

`backend/tests/unit/test_llm_providers.py`:
```python
from app.core.llm import Message, ToolCall
from app.core.llm_providers import _to_anthropic_messages, _to_openai_messages


def test_to_anthropic_messages_converts_user_and_assistant():
    messages = [
        Message(role="user", content="What does main do?"),
        Message(role="assistant", content="It's the entry point."),
    ]
    result = _to_anthropic_messages(messages)
    assert result == [
        {"role": "user", "content": "What does main do?"},
        {"role": "assistant", "content": "It's the entry point."},
    ]


def test_to_anthropic_messages_converts_tool_call_and_result():
    tool_call = ToolCall(id="call_1", name="search_code", arguments={"query": "main"})
    messages = [
        Message(role="assistant", content="", tool_calls=[tool_call]),
        Message(role="tool", content="found it", tool_call_id="call_1"),
    ]
    result = _to_anthropic_messages(messages)
    assert result[0]["role"] == "assistant"
    assert result[0]["content"][0]["type"] == "tool_use"
    assert result[0]["content"][0]["id"] == "call_1"
    assert result[1]["role"] == "user"
    assert result[1]["content"][0]["type"] == "tool_result"
    assert result[1]["content"][0]["tool_use_id"] == "call_1"


def test_to_openai_messages_converts_tool_call_and_result():
    tool_call = ToolCall(id="call_1", name="search_code", arguments={"query": "main"})
    messages = [
        Message(role="assistant", content="", tool_calls=[tool_call]),
        Message(role="tool", content="found it", tool_call_id="call_1"),
    ]
    result = _to_openai_messages(messages)
    assert result[0]["role"] == "assistant"
    assert result[0]["tool_calls"][0]["id"] == "call_1"
    assert result[0]["tool_calls"][0]["function"]["name"] == "search_code"
    assert result[1] == {"role": "tool", "tool_call_id": "call_1", "content": "found it"}
```

- [ ] **Step 6: Run it, verify it passes**

Run: `pytest tests/unit/test_llm_providers.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Add Anthropic/OpenAI LLM clients and provider factory"
```

---

### Task 6: Agent tool — search_code

**Files:**
- Create: `backend/app/core/agent_tools.py`
- Test: `backend/tests/integration/test_agent_tools.py`

**Interfaces:**
- Consumes: `hybrid_search` from `app.core.search` (unchanged), `embed_text` from `app.core.embeddings` (unchanged), `ToolSpec` from `app.core.llm` (Task 4)
- Produces: `SEARCH_CODE_TOOL_SPEC: ToolSpec`, `async def search_code(db: AsyncSession, repo_id: UUID, query: str, limit: int = 5) -> str` — consumed by Task 7 (agent loop) and Task 9 (chat endpoint's `search_fn` closure)

- [ ] **Step 1: Write the failing test**

`backend/tests/integration/test_agent_tools.py`:
```python
import uuid

import pytest

from app.core.agent_tools import search_code
from app.core.embeddings import embed_text
from app.db.models import CodeChunk, NodeType, Repo, RepoStatus, User

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.mark.asyncio
async def test_search_code_returns_formatted_results_with_citations(db_session):
    user = User(email=f"tool-{uuid.uuid4()}@example.com", hashed_password="hashed")
    db_session.add(user)
    await db_session.flush()

    repo = Repo(user_id=user.id, url="https://github.com/example/toolrepo", name="toolrepo", status=RepoStatus.READY)
    db_session.add(repo)
    await db_session.flush()

    content = "def calculate_discount(price, rate):\n    return price * (1 - rate)"
    db_session.add(CodeChunk(
        repo_id=repo.id, file_path="pricing.py", symbol_name="calculate_discount", node_type=NodeType.FUNCTION,
        start_line=10, end_line=11, content=content, embedding=embed_text(content),
    ))
    await db_session.flush()

    result_text = await search_code(db_session, repo.id, "how are discounts calculated")

    assert "pricing.py:10-11" in result_text
    assert "calculate_discount" in result_text
    assert "return price * (1 - rate)" in result_text


@pytest.mark.asyncio
async def test_search_code_returns_no_results_message_when_empty(db_session):
    user = User(email=f"tool-{uuid.uuid4()}@example.com", hashed_password="hashed")
    db_session.add(user)
    await db_session.flush()

    repo = Repo(user_id=user.id, url="https://github.com/example/emptyrepo", name="emptyrepo", status=RepoStatus.READY)
    db_session.add(repo)
    await db_session.flush()

    result_text = await search_code(db_session, repo.id, "anything")
    assert "No matching code found" in result_text
```

- [ ] **Step 2: Run it, verify it fails**

Run: `pytest -m "integration and slow" tests/integration/test_agent_tools.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.core.agent_tools'`)

- [ ] **Step 3: Write `backend/app/core/agent_tools.py`**

```python
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.embeddings import embed_text
from app.core.llm import ToolSpec
from app.core.search import hybrid_search

SEARCH_CODE_TOOL_SPEC = ToolSpec(
    name="search_code",
    description=(
        "Search the repository's code for content relevant to a natural-language "
        "query. Returns ranked code chunks with file path, symbol name, and line "
        "range. Always use this before answering questions about specific code."
    ),
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string", "description": "What to search for"}},
        "required": ["query"],
    },
)


async def search_code(db: AsyncSession, repo_id: UUID, query: str, limit: int = 5) -> str:
    query_embedding = await run_in_threadpool(embed_text, query)
    results = await hybrid_search(db, repo_id, query_text=query, query_embedding=query_embedding, limit=limit)
    if not results:
        return "No matching code found for this query."

    blocks = []
    for r in results:
        symbol = f" ({r.symbol_name})" if r.symbol_name else ""
        blocks.append(f"### {r.file_path}:{r.start_line}-{r.end_line}{symbol}\n```\n{r.content}\n```")
    return "\n\n".join(blocks)
```

- [ ] **Step 4: Run it, verify it passes**

Run: `pytest -m "integration and slow" tests/integration/test_agent_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add search_code agent tool wrapping hybrid_search"
```

---

### Task 7: Agent loop (LangGraph StateGraph)

**Files:**
- Create: `backend/app/core/agent.py`
- Modify: `backend/requirements.txt` (add `langgraph`)
- Test: `backend/tests/unit/test_agent.py`

**Interfaces:**
- Consumes: `LLMClient`, `LLMEvent`, `Message`, `ToolCall` from `app.core.llm` (Task 4); `SEARCH_CODE_TOOL_SPEC` from `app.core.agent_tools` (Task 6)
- Produces: `async def run_agent(llm_client: LLMClient, search_fn: Callable[[str], Awaitable[str]], messages: list[Message]) -> AsyncIterator[LLMEvent]` — consumed by Task 9 (chat endpoint). This public contract is what's tested and what Task 9 depends on; the internal use of `StateGraph` is an implementation detail behind it (see the risk note in Step 3).

**Known risk, read before starting:** this design streams tokens out of a LangGraph node in real time using `langgraph.config.get_stream_writer()` with `graph.astream(state, stream_mode="custom")` — an API that was added to LangGraph around the 0.2.20+ line. `requirements.txt` pins `langgraph==0.2.45`, where it should exist, but if `from langgraph.config import get_stream_writer` fails to import, or `stream_mode="custom"` isn't accepted by the installed version:
1. First check the actual installed version's docs/source for the correct import path — it may have moved (e.g. `langgraph.types`) rather than being missing.
2. If it's genuinely unavailable, fall back to implementing `run_agent` as a plain `async def` generator function containing the same node logic (the `assistant`/`tools` step logic below) inlined into a single loop, *without* wrapping it in a `StateGraph` — same public signature, same yielded event sequence, same `MAX_TOOL_ITERATIONS` cap. Document clearly in your report which path you took and why; this is a legitimate, anticipated fallback, not a corner cut.
The tests in Step 5 test `run_agent`'s public behavior only (input messages + a `FakeLLMClient` script → output event sequence) — they pass identically regardless of which internal implementation is used, so switching to the fallback does not require rewriting the tests.

- [ ] **Step 1: Add the dependency**

In `backend/requirements.txt`, add:
```
langgraph==0.2.45
```
Install: `pip install -r requirements.txt` (from `backend/`, venv activated). Verify the streaming API this task needs actually exists in what got installed:
```bash
python -c "from langgraph.config import get_stream_writer; print('ok')"
```
If this fails, read the risk note above before writing `agent.py`.

- [ ] **Step 2: Write the failing test**

`backend/tests/unit/test_agent.py`:
```python
import pytest

from app.core.agent import run_agent
from app.core.llm import FakeLLMClient, Message, ScriptedTurn, ToolCall


async def _no_op_search(query: str) -> str:
    return f"no results for {query}"


@pytest.mark.asyncio
async def test_run_agent_streams_tokens_and_terminates_on_message_done():
    client = FakeLLMClient(turns=[ScriptedTurn(text="The answer is 42")])
    events = [
        event async for event in run_agent(client, _no_op_search, [Message(role="user", content="what is the answer")])
    ]

    assert any(e.type == "token" for e in events)
    assert events[-1].type == "message_done"
    assert events[-1].message.content == "The answer is 42"


@pytest.mark.asyncio
async def test_run_agent_executes_tool_call_then_continues():
    tool_call = ToolCall(id="call_1", name="search_code", arguments={"query": "auth"})
    client = FakeLLMClient(
        turns=[
            ScriptedTurn(tool_calls=[tool_call]),
            ScriptedTurn(text="Found it in auth.py"),
        ]
    )

    captured_queries = []

    async def search_fn(query: str) -> str:
        captured_queries.append(query)
        return "auth.py:1-5 has the login function"

    events = [event async for event in run_agent(client, search_fn, [Message(role="user", content="how does auth work")])]

    assert captured_queries == ["auth"]
    event_types = [e.type for e in events]
    assert "tool_call" in event_types
    assert "tool_result" in event_types
    assert event_types[-1] == "message_done"
    assert events[-1].message.content == "Found it in auth.py"


@pytest.mark.asyncio
async def test_run_agent_propagates_llm_error():
    from app.core.llm import LLMEvent

    class ErroringClient:
        async def stream_chat(self, messages, tools, system_prompt):
            yield LLMEvent(type="error", error="rate limited")

    events = [event async for event in run_agent(ErroringClient(), _no_op_search, [Message(role="user", content="hi")])]
    assert events[-1].type == "error"
    assert events[-1].error == "rate limited"


@pytest.mark.asyncio
async def test_run_agent_gives_up_gracefully_after_max_iterations():
    # Every turn is a tool call, forever -- the agent should stop after
    # MAX_TOOL_ITERATIONS rounds with a real message_done, not hang or crash.
    turns = [ScriptedTurn(tool_calls=[ToolCall(id=f"call_{i}", name="search_code", arguments={"query": "x"})]) for i in range(10)]
    client = FakeLLMClient(turns=turns)

    events = [event async for event in run_agent(client, _no_op_search, [Message(role="user", content="loop forever")])]

    assert events[-1].type == "message_done"
    assert events[-1].message.content  # some explanatory text, not empty
```

- [ ] **Step 3: Run it, verify it fails**

Run: `pytest tests/unit/test_agent.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.core.agent'`)

- [ ] **Step 4: Write `backend/app/core/agent.py`**

```python
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph

from app.core.agent_tools import SEARCH_CODE_TOOL_SPEC
from app.core.llm import LLMClient, LLMEvent, Message, ToolCall

SYSTEM_PROMPT = (
    "You are a code assistant answering questions about a specific GitHub "
    "repository. Use the search_code tool to find relevant code before "
    "answering -- never guess at code you haven't seen. When you reference "
    "code in your answer, always cite it as `path/to/file.py:12-18` (the "
    "file path and line range). If the search results don't contain enough "
    "information to answer confidently, say so rather than speculating."
)

MAX_TOOL_ITERATIONS = 5

SearchFn = Callable[[str], Awaitable[str]]


class AgentState(TypedDict):
    messages: list[Message]
    iterations: int
    done: bool


def _build_graph(llm_client: LLMClient, search_fn: SearchFn):
    async def assistant_node(state: AgentState) -> dict:
        writer = get_stream_writer()

        if state["iterations"] >= MAX_TOOL_ITERATIONS:
            message = Message(
                role="assistant",
                content=(
                    "I wasn't able to finish researching this within the allowed "
                    "number of search steps. Could you narrow your question?"
                ),
            )
            writer(LLMEvent(type="message_done", message=message))
            return {"messages": [*state["messages"], message], "done": True}

        tool_calls: list[ToolCall] = []
        final_message: Message | None = None
        errored = False

        async for event in llm_client.stream_chat(
            state["messages"], tools=[SEARCH_CODE_TOOL_SPEC], system_prompt=SYSTEM_PROMPT
        ):
            writer(event)
            if event.type == "tool_call":
                tool_calls = event.tool_calls or []
            elif event.type == "message_done":
                final_message = event.message
            elif event.type == "error":
                errored = True

        if errored:
            return {"done": True}
        if tool_calls:
            return {
                "messages": [*state["messages"], Message(role="assistant", content="", tool_calls=tool_calls)],
                "iterations": state["iterations"] + 1,
            }
        if final_message is not None:
            return {"messages": [*state["messages"], final_message], "done": True}
        return {"done": True}

    async def tools_node(state: AgentState) -> dict:
        writer = get_stream_writer()
        last_message = state["messages"][-1]
        new_messages = list(state["messages"])
        for tool_call in last_message.tool_calls:
            if tool_call.name == "search_code":
                try:
                    result_text = await search_fn(tool_call.arguments.get("query", ""))
                except Exception as exc:
                    result_text = f"search_code failed: {exc}"
            else:
                result_text = f"Unknown tool: {tool_call.name}"
            writer(LLMEvent(type="tool_result", tool_calls=[tool_call], tool_result_text=result_text))
            new_messages.append(Message(role="tool", content=result_text, tool_call_id=tool_call.id))
        return {"messages": new_messages}

    def route_after_assistant(state: AgentState) -> str:
        if state.get("done"):
            return END
        last_message = state["messages"][-1]
        if last_message.role == "assistant" and last_message.tool_calls:
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("assistant", assistant_node)
    graph.add_node("tools", tools_node)
    graph.set_entry_point("assistant")
    graph.add_conditional_edges("assistant", route_after_assistant, {"tools": "tools", END: END})
    graph.add_edge("tools", "assistant")
    return graph.compile()


async def run_agent(llm_client: LLMClient, search_fn: SearchFn, messages: list[Message]) -> AsyncIterator[LLMEvent]:
    graph = _build_graph(llm_client, search_fn)
    initial_state: AgentState = {"messages": messages, "iterations": 0, "done": False}
    async for event in graph.astream(initial_state, stream_mode="custom"):
        yield event
```

- [ ] **Step 5: Run it, verify it passes**

Run: `pytest tests/unit/test_agent.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add LangGraph-based agent loop with streaming tool-call orchestration"
```

---

### Task 8: Conversations API

**Files:**
- Modify: `backend/app/api/deps.py` (add `get_owned_conversation` shared helper)
- Create: `backend/app/schemas/chat.py`
- Create: `backend/app/api/routes/conversations.py`
- Modify: `backend/app/main.py` (wire the new router)
- Test: `backend/tests/integration/test_conversations_api.py`

**Interfaces:**
- Consumes: `get_owned_repo` from `app.api.deps` (Task 3); `Conversation`, `Message`, `MessageRole` from `app.db.models` (Task 1)
- Produces: `async def get_owned_conversation(db, conversation_id, user) -> Conversation` in `app.api.deps` — consumed by Task 9
- Produces routes: `POST/GET /api/v1/repos/{repo_id}/conversations`, `GET /api/v1/conversations/{id}/messages`

- [ ] **Step 1: Add `get_owned_conversation` to `backend/app/api/deps.py`**

Add `Conversation` to the existing `from app.db.models import Repo` import line, making it:
```python
from app.db.models import Conversation, Repo
```
Add this function after `get_owned_repo`:
```python
async def get_owned_conversation(db: AsyncSession, conversation_id: UUID, user: User) -> Conversation:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation
```

- [ ] **Step 2: Write `backend/app/schemas/chat.py`**

```python
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", min_length=1, max_length=255)


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repo_id: uuid.UUID
    title: str
    created_at: datetime


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    created_at: datetime


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
```

- [ ] **Step 3: Write `backend/app/api/routes/conversations.py`**

```python
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_owned_conversation, get_owned_repo
from app.db.models import Conversation, Message, User
from app.db.session import get_db
from app.schemas.chat import ConversationCreate, ConversationResponse, MessageResponse

router = APIRouter(prefix="/api/v1", tags=["conversations"])


@router.post("/repos/{repo_id}/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    repo_id: UUID,
    payload: ConversationCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Conversation:
    await get_owned_repo(db, repo_id, current_user)
    conversation = Conversation(repo_id=repo_id, user_id=current_user.id, title=payload.title)
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.get("/repos/{repo_id}/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    repo_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Conversation]:
    await get_owned_repo(db, repo_id, current_user)
    result = await db.execute(
        select(Conversation)
        .where(Conversation.repo_id == repo_id, Conversation.user_id == current_user.id)
        .order_by(Conversation.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
async def get_messages(
    conversation_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Message]:
    conversation = await get_owned_conversation(db, conversation_id, current_user)
    result = await db.execute(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)
    )
    return list(result.scalars().all())
```

- [ ] **Step 4: Wire the router into main.py**

In `backend/app/main.py`, replace:
```python
from app.api.routes import auth, files, jobs, repos, search
```
with:
```python
from app.api.routes import auth, conversations, files, jobs, repos, search
```
and replace:
```python
app.include_router(files.router)
```
with:
```python
app.include_router(files.router)
app.include_router(conversations.router)
```

- [ ] **Step 5: Write the test**

`backend/tests/integration/test_conversations_api.py`:
```python
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import Repo, RepoStatus
from app.db.session import async_session_maker
from app.main import app

pytestmark = pytest.mark.integration


async def _register_and_login(client: AsyncClient) -> str:
    email = f"conv-{uuid.uuid4()}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
    login_resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
    return login_resp.json()["access_token"]


async def _create_repo_for_user(user_id: str, url: str) -> str:
    async with async_session_maker() as db:
        repo = Repo(user_id=user_id, url=url, name="repo", status=RepoStatus.READY)
        db.add(repo)
        await db.commit()
        return str(repo.id)


@pytest.mark.asyncio
async def test_create_list_conversations_and_empty_message_history():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        me_resp = await client.get("/api/v1/auth/me", headers=headers)
        user_id = me_resp.json()["id"]
        repo_id = await _create_repo_for_user(user_id, "https://github.com/example/convrepo")

        create_resp = await client.post(
            f"/api/v1/repos/{repo_id}/conversations", json={"title": "First chat"}, headers=headers
        )
        assert create_resp.status_code == 201
        conversation_id = create_resp.json()["id"]

        list_resp = await client.get(f"/api/v1/repos/{repo_id}/conversations", headers=headers)
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1
        assert list_resp.json()[0]["title"] == "First chat"

        messages_resp = await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers)
        assert messages_resp.status_code == 200
        assert messages_resp.json() == []


@pytest.mark.asyncio
async def test_conversation_endpoints_reject_other_users():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        owner_token = await _register_and_login(client)
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        owner_me = await client.get("/api/v1/auth/me", headers=owner_headers)
        owner_id = owner_me.json()["id"]
        repo_id = await _create_repo_for_user(owner_id, "https://github.com/example/privateconv")

        create_resp = await client.post(
            f"/api/v1/repos/{repo_id}/conversations", json={"title": "Private"}, headers=owner_headers
        )
        conversation_id = create_resp.json()["id"]

        other_token = await _register_and_login(client)
        other_headers = {"Authorization": f"Bearer {other_token}"}

        assert (await client.get(f"/api/v1/repos/{repo_id}/conversations", headers=other_headers)).status_code == 404
        assert (
            await client.post(f"/api/v1/repos/{repo_id}/conversations", json={"title": "x"}, headers=other_headers)
        ).status_code == 404
        assert (
            await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=other_headers)
        ).status_code == 404
```

- [ ] **Step 6: Run it, verify it passes**

Run: `pytest -m integration tests/integration/test_conversations_api.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Add conversations CRUD API"
```

---

### Task 9: Chat streaming endpoint (SSE)

**Files:**
- Create: `backend/app/api/routes/chat.py`
- Modify: `backend/app/main.py` (wire the new router)
- Test: `backend/tests/integration/test_chat_api.py`

**Interfaces:**
- Consumes: `get_owned_conversation` from `app.api.deps` (Task 8); `run_agent` from `app.core.agent` (Task 7); `search_code` from `app.core.agent_tools` (Task 6); `get_llm_client` from `app.core.llm_providers` (Task 5); `Message` (as `AgentMessage`) from `app.core.llm` (Task 4); `Message`, `MessageRole` from `app.db.models` (Task 1)
- Produces route: `POST /api/v1/conversations/{conversation_id}/messages` — SSE stream (`text/event-stream`), event types `token`, `tool_call`, `tool_result`, `done`, `error`

- [ ] **Step 1: Write `backend/app/api/routes/chat.py`**

```python
import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_owned_conversation
from app.core.agent import run_agent
from app.core.agent_tools import search_code
from app.core.llm import Message as AgentMessage
from app.core.llm_providers import get_llm_client
from app.db.models import Message, MessageRole, User
from app.db.session import async_session_maker, get_db
from app.schemas.chat import SendMessageRequest

router = APIRouter(prefix="/api/v1", tags=["chat"])


def _db_role_to_agent_role(role: MessageRole) -> str:
    return "user" if role == MessageRole.USER else "assistant"


async def _load_history(db: AsyncSession, conversation_id: UUID) -> list[AgentMessage]:
    result = await db.execute(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
    )
    return [AgentMessage(role=_db_role_to_agent_role(m.role), content=m.content) for m in result.scalars().all()]


def _sse_event(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: UUID,
    payload: SendMessageRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    conversation = await get_owned_conversation(db, conversation_id, current_user)
    repo_id = conversation.repo_id
    conversation_id_value = conversation.id

    history = await _load_history(db, conversation_id_value)

    user_message = Message(conversation_id=conversation_id_value, role=MessageRole.USER, content=payload.content)
    db.add(user_message)
    await db.commit()

    async def event_stream() -> AsyncIterator[str]:
        try:
            llm_client = get_llm_client()
        except RuntimeError as exc:
            yield _sse_event("error", {"message": str(exc)})
            return

        conversation_messages = [*history, AgentMessage(role="user", content=payload.content)]

        async def search_fn(query: str) -> str:
            async with async_session_maker() as search_db:
                return await search_code(search_db, repo_id, query)

        assistant_text = ""
        try:
            async for event in run_agent(llm_client, search_fn, conversation_messages):
                if event.type == "token":
                    assistant_text += event.token or ""
                    yield _sse_event("token", {"text": event.token})
                elif event.type == "tool_call":
                    query = event.tool_calls[0].arguments.get("query", "") if event.tool_calls else ""
                    yield _sse_event("tool_call", {"query": query})
                elif event.type == "tool_result":
                    summary = (event.tool_result_text or "")[:200]
                    yield _sse_event("tool_result", {"summary": summary})
                elif event.type == "message_done":
                    final_text = event.message.content if event.message else assistant_text
                    async with async_session_maker() as save_db:
                        assistant_message = Message(
                            conversation_id=conversation_id_value, role=MessageRole.ASSISTANT, content=final_text
                        )
                        save_db.add(assistant_message)
                        await save_db.commit()
                        await save_db.refresh(assistant_message)
                    yield _sse_event("done", {"message_id": str(assistant_message.id)})
                elif event.type == "error":
                    yield _sse_event("error", {"message": event.error or "The assistant hit an unexpected error."})
        except Exception as exc:
            yield _sse_event("error", {"message": f"Unexpected error: {exc}"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

- [ ] **Step 2: Wire the router into main.py**

In `backend/app/main.py`, replace:
```python
from app.api.routes import auth, conversations, files, jobs, repos, search
```
with:
```python
from app.api.routes import auth, chat, conversations, files, jobs, repos, search
```
and replace:
```python
app.include_router(conversations.router)
```
with:
```python
app.include_router(conversations.router)
app.include_router(chat.router)
```

- [ ] **Step 3: Write the test**

This test replaces the real LLM client with `FakeLLMClient` by monkeypatching `get_llm_client` in the `chat` module — no network, no real key needed, deterministic.

`backend/tests/integration/test_chat_api.py`:
```python
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import Repo, RepoStatus
from app.db.session import async_session_maker
from app.main import app

pytestmark = pytest.mark.integration


async def _register_and_login(client: AsyncClient) -> tuple[str, str]:
    email = f"chat-{uuid.uuid4()}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
    login_resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
    token = login_resp.json()["access_token"]
    me_resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return token, me_resp.json()["id"]


async def _create_repo(user_id: str) -> str:
    async with async_session_maker() as db:
        repo = Repo(user_id=user_id, url=f"https://github.com/example/chatrepo-{uuid.uuid4()}", name="chatrepo", status=RepoStatus.READY)
        db.add(repo)
        await db.commit()
        return str(repo.id)


def _parse_sse_events(raw_text: str) -> list[dict]:
    events = []
    for block in raw_text.strip().split("\n\n"):
        if not block.strip():
            continue
        lines = block.strip().split("\n")
        event_type = lines[0].removeprefix("event: ")
        import json as _json

        data = _json.loads(lines[1].removeprefix("data: "))
        events.append({"type": event_type, "data": data})
    return events


@pytest.mark.asyncio
async def test_send_message_streams_response_and_persists_messages(monkeypatch):
    from app.core.llm import FakeLLMClient, ScriptedTurn

    monkeypatch.setattr(
        "app.api.routes.chat.get_llm_client",
        lambda: FakeLLMClient(turns=[ScriptedTurn(text="The repo looks fine.")]),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, user_id = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        repo_id = await _create_repo(user_id)

        conv_resp = await client.post(f"/api/v1/repos/{repo_id}/conversations", json={"title": "Chat"}, headers=headers)
        conversation_id = conv_resp.json()["id"]

        async with client.stream(
            "POST",
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "Is the repo healthy?"},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            raw = ""
            async for chunk in response.aiter_text():
                raw += chunk

        events = _parse_sse_events(raw)
        assert any(e["type"] == "token" for e in events)
        assert events[-1]["type"] == "done"

        messages_resp = await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers)
        messages = messages_resp.json()
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Is the repo healthy?"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "The repo looks fine."


@pytest.mark.asyncio
async def test_send_message_surfaces_llm_error_as_sse_error_event(monkeypatch):
    from app.core.llm import LLMEvent

    class ErroringClient:
        async def stream_chat(self, messages, tools, system_prompt):
            yield LLMEvent(type="error", error="upstream LLM API is down")

    monkeypatch.setattr("app.api.routes.chat.get_llm_client", lambda: ErroringClient())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, user_id = await _register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        repo_id = await _create_repo(user_id)
        conv_resp = await client.post(f"/api/v1/repos/{repo_id}/conversations", json={"title": "Chat"}, headers=headers)
        conversation_id = conv_resp.json()["id"]

        async with client.stream(
            "POST",
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "hello"},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            raw = ""
            async for chunk in response.aiter_text():
                raw += chunk

        events = _parse_sse_events(raw)
        assert events[-1]["type"] == "error"
        assert "upstream LLM API is down" in events[-1]["data"]["message"]

        # The user's message is still persisted even though the assistant failed.
        messages_resp = await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers)
        messages = messages_resp.json()
        assert len(messages) == 1
        assert messages[0]["role"] == "user"


@pytest.mark.asyncio
async def test_send_message_rejects_other_users_conversation(monkeypatch):
    from app.core.llm import FakeLLMClient, ScriptedTurn

    monkeypatch.setattr(
        "app.api.routes.chat.get_llm_client", lambda: FakeLLMClient(turns=[ScriptedTurn(text="hi")])
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        owner_token, owner_id = await _register_and_login(client)
        repo_id = await _create_repo(owner_id)
        conv_resp = await client.post(
            f"/api/v1/repos/{repo_id}/conversations", json={"title": "Chat"}, headers={"Authorization": f"Bearer {owner_token}"}
        )
        conversation_id = conv_resp.json()["id"]

        other_token, _ = await _register_and_login(client)
        resp = await client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "hi"},
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 404
```

- [ ] **Step 4: Run it, verify it passes**

Run: `pytest -m integration tests/integration/test_chat_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add SSE-streamed chat endpoint wired to the agent loop"
```

---

### Task 10: README updates

**Files:**
- Modify: `backend/../README.md` (root README from sub-project 1)

- [ ] **Step 1: Update the README**

In the root `README.md`, add a new section after the existing "Example walkthrough" section (before "Non-goals in this phase" / "Known limitations"):

```markdown
## Chat with a repo (sub-project 2A)

Once a repo has finished analyzing, you can open a conversation and ask
questions about it. This requires a real LLM API key (Anthropic or
OpenAI) — without one, the chat endpoint returns a clean SSE `error`
event rather than crashing, but won't produce real answers.

1. Add to `backend/.env`:
   ```
   LLM_PROVIDER=anthropic
   ANTHROPIC_API_KEY=sk-ant-...
   ```
   (or `LLM_PROVIDER=openai` with `OPENAI_API_KEY=...`)
2. Restart the API (and worker, if running) so the new env vars are picked up.
3. Browse the file tree: `curl http://localhost:8000/api/v1/repos/<repo_id>/files -H "Authorization: Bearer <token>"`
4. Start a conversation:
   ```bash
   curl -X POST http://localhost:8000/api/v1/repos/<repo_id>/conversations \
     -H "Content-Type: application/json" -H "Authorization: Bearer <token>" \
     -d '{"title": "First chat"}'
   # -> {"id": "<conversation_id>", ...}
   ```
5. Send a message and watch the streamed response (SSE — `curl -N` to disable buffering):
   ```bash
   curl -N -X POST http://localhost:8000/api/v1/conversations/<conversation_id>/messages \
     -H "Content-Type: application/json" -H "Authorization: Bearer <token>" \
     -d '{"content": "What does this repo do?"}'
   ```
   You should see `event: tool_call`, `event: tool_result`, a stream of
   `event: token`, and a final `event: done` — with the assistant citing
   real files and line numbers from the repo.

This manual walkthrough is the only place this sub-project talks to a
real LLM API — all automated tests use a deterministic fake client (see
`docs/superpowers/specs/2026-08-16-agent-engine-design.md`).
```

- [ ] **Step 2: Commit**

```bash
git add -A
git commit -m "Document chat setup and manual LLM smoke test in README"
```
