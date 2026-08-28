import gc
import sys
from dataclasses import dataclass
from pathlib import Path

import git

from app.core.chunker import Chunk, chunk_file
from app.core.embeddings import embed_texts

EXCLUDED_DIR_PATTERNS = {
    ".git", "node_modules", "dist", "build", "__pycache__", ".venv", "venv",
    ".next", "target", "vendor", ".pytest_cache",
}
# Confirmed live: this free-tier deployment's 512MB budget is tight enough
# that a single very large file's content sitting in memory (once as the
# raw read, again in the CodeChunk/File rows built from it) is worth
# bounding tightly, not just capping file *count*. 300KB comfortably covers
# the overwhelming majority of real hand-written source files -- what it
# excludes is almost always a generated/vendored/data file anyway, which
# read_file/search_code would truncate at query time regardless (see
# token_budget.py). Down from 1MB.
MAX_FILE_SIZE_BYTES = 300_000

# Extension-based skip for common binary asset types. Checked before
# attempting path.read_text() -- previously these were only caught
# indirectly via UnicodeDecodeError after a failed read attempt (or the size
# cap, for large ones), which wastes a read syscall and a decode attempt on
# every one of these files in a repo that often has plenty of them (images,
# fonts, bundled media).
_BINARY_EXTENSIONS = {
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp", ".bmp",
    # Fonts
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    # Media
    ".mp4", ".mov", ".mp3", ".wav",
    # Archives / binaries
    ".zip", ".tar", ".gz", ".exe", ".dll", ".so", ".bin", ".pdf", ".class", ".jar", ".pyc",
}


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
    # GitPython's kill_after_timeout is unconditionally unsupported on
    # Windows: passing any non-None value makes Git.execute() raise
    # GitCommandError immediately, before the clone even starts (see
    # git/cmd.py's `sys.platform == "win32"` guard). This service deploys on
    # Linux, where the flag works as intended, so it's only omitted on
    # win32 to keep local dev/test clones (and CI running on Windows
    # runners, if any) functional.
    clone_kwargs = {} if sys.platform == "win32" else {"kill_after_timeout": timeout_seconds}
    try:
        git.Repo.clone_from(
            url,
            dest_dir,
            depth=1,
            single_branch=True,
            # Without this, a private/misauthenticated repo makes git prompt
            # interactively for credentials -- a prompt nothing can ever
            # answer in a background worker, hanging the clone indefinitely
            # regardless of kill_after_timeout racing it. Disabling the
            # prompt makes auth failures fail fast as a normal GitCommandError.
            env={"GIT_TERMINAL_PROMPT": "0"},
            **clone_kwargs,
        )
    except git.GitCommandError as exc:
        raise CloneError(f"Failed to clone {url}: {exc}") from exc

    total_size_mb = sum(f.stat().st_size for f in dest_dir.rglob("*") if f.is_file()) / (1024 * 1024)
    if total_size_mb > max_size_mb:
        raise RepoTooLargeError(f"Repo size {total_size_mb:.1f}MB exceeds cap of {max_size_mb}MB")

    return dest_dir


def _should_skip_dir(dir_name: str) -> bool:
    return dir_name in EXCLUDED_DIR_PATTERNS or dir_name.startswith(".")


def _is_likely_binary(path: Path) -> bool:
    return path.suffix.lower() in _BINARY_EXTENSIONS


def walk_and_chunk(root_dir: Path, max_files: int, skip_chunking: bool = False) -> WalkResult:
    """Walks `root_dir`, reading and AST-chunking every eligible file.

    `skip_chunking=True` (passed by tasks.py when Settings.enable_embedding
    is False) skips the tree-sitter parse (chunker.chunk_file) entirely --
    those chunks only ever feed the embedding step, so computing them at
    all when embedding is disabled is pure wasted CPU/memory for a result
    nothing will ever read. Confirmed live: this deployment already runs
    with embedding disabled by default (see render.yaml's ENABLE_EMBEDDING),
    so this isn't a hypothetical saving -- it applies to every real
    analysis run today.
    """
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

        # Symlinked files must never be followed: `is_dir()` is False for a
        # symlink pointing at a file, so it would otherwise sail through the
        # checks below and `read_text()` would happily follow it and read
        # whatever it points at (e.g. a secret mounted outside the clone).
        if path.is_symlink():
            files_skipped += 1
            continue

        # Defense in depth: even without a direct symlink, a resolved path
        # (e.g. via a symlinked parent directory, or other filesystem
        # trickery) could still land outside the clone root. Refuse to read
        # anything that doesn't resolve back under root_dir.
        try:
            if not path.resolve().is_relative_to(resolved_root):
                files_skipped += 1
                continue
        except OSError:
            files_skipped += 1
            continue

        if _is_likely_binary(path):
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

        # A NUL byte is legal UTF-8 (it's just codepoint U+0000), so
        # read_text() above doesn't reject it -- but Postgres's text/varchar
        # columns categorically cannot store one (its storage is
        # C-string-based internally), regardless of encoding validity.
        # Confirmed live: a handful of test-fixture files in a real repo
        # (github/linguist's sample corpus) contain embedded NULs and blew
        # up the batch File insert with an unhandled asyncpg
        # CharacterNotInRepertoireError. Treated the same as any other
        # "not real source text" file -- skipped here, before it ever
        # reaches chunking or the DB.
        if "\x00" in source:
            files_skipped += 1
            continue

        try:
            relative_path = str(path.relative_to(root_dir)).replace("\\", "/")
            if not skip_chunking:
                all_chunks.extend(chunk_file(relative_path, source))
            all_files.append(WalkedFile(path=relative_path, content=source))
            files_processed += 1
        except Exception:
            files_skipped += 1
            continue

    # Explicit collection rather than waiting for the next scheduled GC
    # cycle: this function alone can allocate (and, for most of that walk,
    # hold live) tens of thousands of short-lived tree-sitter parse-tree
    # objects and intermediate strings across a large repo -- on a 512MB
    # budget, returning that memory to the allocator promptly (instead of
    # whenever Python's generational GC would otherwise get around to it)
    # measurably lowers this function's own peak RSS contribution.
    gc.collect()

    return WalkResult(chunks=all_chunks, files=all_files, files_processed=files_processed, files_skipped=files_skipped)


def embed_chunks(chunks: list[Chunk], batch_size: int = 8) -> list[ChunkWithEmbedding]:
    if not chunks:
        return []
    embeddings = embed_texts([c.content for c in chunks], batch_size=batch_size)
    return [ChunkWithEmbedding(chunk=c, embedding=e) for c, e in zip(chunks, embeddings)]


# Prose/docs never carry the kind of code semantics search_code's embedding
# search is for -- excluded from embedding entirely (they're still fully
# stored as File rows regardless, so list_directory/read_file work on them
# same as any other file; this only affects the embedding step's scope).
NON_EMBEDDABLE_EXTENSIONS = {".md", ".markdown", ".rst", ".txt", ".adoc", ".mdx"}


def select_chunks_for_embedding(chunks: list[Chunk], max_files: int, max_chunks: int) -> list[Chunk]:
    # Bulk CodeBERT embedding is the dominant cost in analysis -- confirmed
    # live this session, minutes of sustained near-100%-CPU for a real
    # medium-sized repo. Capping *files* alone isn't actually sufficient: a
    # repo's 15 most substantive files (by the same ranking used here) can
    # still carry hundreds of chunks between them for a large real project
    # (confirmed live: lodash's top-15 files alone kept embedding running
    # 100+ seconds under this cap without max_chunks) -- so this caps BOTH.
    # list_directory/read_file (app/core/agent_tools.py) give the chat agent
    # a way to inspect any file directly even if it was never embedded --
    # search_code just won't surface it by keyword/semantic search.
    eligible_by_file: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        ext = Path(chunk.file_path).suffix.lower()
        if ext in NON_EMBEDDABLE_EXTENSIONS:
            continue
        eligible_by_file.setdefault(chunk.file_path, []).append(chunk)

    # Rank files by total chunked content length, descending -- a cheap
    # proxy for "substantive": a file with more/larger parsed symbols is
    # more likely to be load-bearing than e.g. a tiny stub or a generated
    # constants file. Ties (e.g. all-empty) keep dict insertion order, which
    # is file-discovery order from the walk -- stable, not random.
    ranked_paths = sorted(
        eligible_by_file, key=lambda p: sum(len(c.content) for c in eligible_by_file[p]), reverse=True
    )[:max_files]

    # Walk the ranked files in order, taking whole files' worth of chunks
    # until the total chunk budget runs out -- a file that would blow the
    # budget is skipped entirely rather than truncated mid-file, so no
    # chunk is ever embedded without the rest of its immediate neighbors
    # (e.g. a function chunk without the sibling chunks around it would be
    # a confusing, partial view for search_code to surface).
    selected: list[Chunk] = []
    for path in ranked_paths:
        file_chunks = eligible_by_file[path]
        if len(selected) + len(file_chunks) > max_chunks:
            if selected:
                break
            # Even the single largest file alone exceeds the budget --
            # still cap at max_chunks rather than embedding nothing at all.
            selected.extend(file_chunks[:max_chunks])
            break
        selected.extend(file_chunks)
    return selected


def ingest_local_directory(root_dir: Path, max_files: int) -> IngestionResult:
    walk_result = walk_and_chunk(root_dir, max_files)
    embedded = embed_chunks(walk_result.chunks)
    return IngestionResult(
        chunks=embedded,
        files=walk_result.files,
        files_processed=walk_result.files_processed,
        files_skipped=walk_result.files_skipped,
    )
