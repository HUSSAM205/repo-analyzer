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
