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
MAX_FILE_SIZE_BYTES = 1_000_000

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


# Prose/docs never carry the kind of code semantics search_code's embedding
# search is for -- excluded from embedding entirely (they're still fully
# stored as File rows regardless, so list_directory/read_file work on them
# same as any other file; this only affects the embedding step's scope).
NON_EMBEDDABLE_EXTENSIONS = {".md", ".markdown", ".rst", ".txt", ".adoc", ".mdx"}


def select_chunks_for_embedding(chunks: list[Chunk], max_files: int) -> list[Chunk]:
    # Bulk CodeBERT embedding is the dominant cost in analysis -- confirmed
    # live this session, minutes of sustained near-100%-CPU for a real
    # medium-sized repo. Capping which *files* get embedded (not truncating
    # chunks within a file) bounds that cost to a small, predictable number
    # regardless of repo size, while list_directory/read_file (added
    # separately) give the chat agent a way to inspect any file directly
    # even if it was never embedded -- search_code just won't surface it by
    # keyword/semantic search.
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
    ranked_set = set(ranked_paths)
    return [c for c in chunks if c.file_path in ranked_set]


def ingest_local_directory(root_dir: Path, max_files: int) -> IngestionResult:
    walk_result = walk_and_chunk(root_dir, max_files)
    embedded = embed_chunks(walk_result.chunks)
    return IngestionResult(
        chunks=embedded,
        files=walk_result.files,
        files_processed=walk_result.files_processed,
        files_skipped=walk_result.files_skipped,
    )
