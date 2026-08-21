import shutil
from pathlib import Path

import pytest

from app.core.chunker import Chunk
from app.core.ingestion import _is_likely_binary, ingest_local_directory, select_chunks_for_embedding, walk_and_chunk

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "sample_repo"


def _chunk(file_path: str, content: str = "x") -> Chunk:
    return Chunk(file_path=file_path, symbol_name=None, node_type="function", start_line=1, end_line=1, content=content)


def test_walk_and_chunk_processes_all_fixture_files():
    result = walk_and_chunk(FIXTURE_DIR, max_files=100)
    assert result.files_processed == 3
    assert result.files_skipped == 0
    assert len(result.files) == 3
    symbol_names = {c.symbol_name for c in result.chunks if c.symbol_name}
    assert "greet" in symbol_names
    assert "Greeter" in symbol_names
    assert "add" in symbol_names


def test_walk_and_chunk_respects_max_files():
    result = walk_and_chunk(FIXTURE_DIR, max_files=1)
    assert result.files_processed == 1


def test_walk_and_chunk_skips_symlink_pointing_outside_root(tmp_path):
    # A file outside the directory being analyzed, standing in for something
    # sensitive (e.g. a JWT private key mounted elsewhere in the container).
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    secret_file = outside_dir / "secret.pem"
    secret_file.write_text("-----BEGIN PRIVATE KEY-----\nSUPER_SECRET_KEY_MATERIAL\n-----END PRIVATE KEY-----\n")

    # Copy the fixture repo into a throwaway directory so we can plant a
    # symlink inside it without touching the real fixtures.
    repo_dir = tmp_path / "repo"
    shutil.copytree(FIXTURE_DIR, repo_dir)
    symlink_path = repo_dir / "sneaky_link.py"

    # Whether os.symlink is permitted depends on OS privileges (admin rights
    # or Developer Mode on Windows) that can't be reliably determined ahead
    # of time at collection, so we attempt creation and skip at runtime with
    # a clear reason if it's not permitted in this environment. The
    # production fix in walk_and_chunk does not depend on being able to
    # exercise it here.
    try:
        symlink_path.symlink_to(secret_file)
    except OSError as exc:
        pytest.skip(f"cannot create symlinks in this environment (requires elevated privileges): {exc}")

    result = walk_and_chunk(repo_dir, max_files=100)

    # Only the three legitimate fixture files should be processed; the
    # symlink must be skipped, not read, not chunked.
    assert result.files_processed == 3
    assert result.files_skipped == 1
    assert not any("SUPER_SECRET_KEY_MATERIAL" in c.content for c in result.chunks)
    assert not any(c.file_path == "sneaky_link.py" for c in result.chunks)
    assert not any("SUPER_SECRET_KEY_MATERIAL" in f.content for f in result.files)


def test_walk_and_chunk_skips_file_that_resolves_outside_root(tmp_path):
    # Defense-in-depth check: even if a path isn't itself a symlink, one
    # whose resolved location escapes the clone root must still be skipped
    # (e.g. reached via a symlinked parent directory).
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    secret_file = outside_dir / "secret.txt"
    secret_file.write_text("outside content")

    repo_dir = tmp_path / "repo2"
    repo_dir.mkdir()
    linked_subdir = repo_dir / "linked"

    try:
        linked_subdir.symlink_to(outside_dir, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"cannot create symlinks in this environment (requires elevated privileges): {exc}")

    result = walk_and_chunk(repo_dir, max_files=100)

    assert not any("outside content" in c.content for c in result.chunks)
    assert result.files_processed == 0


def test_walk_and_chunk_skips_symlink_via_monkeypatch(tmp_path, monkeypatch):
    # Creating real symlinks requires elevated privileges that this Windows
    # environment doesn't have (see the two tests above, which skip here for
    # that reason). This test exercises the same production code path
    # deterministically by forcing Path.is_symlink() to report True for one
    # specific file, without needing OS-level symlink support, so the skip
    # logic itself is still verified end-to-end in this environment.
    repo_dir = tmp_path / "repo3"
    shutil.copytree(FIXTURE_DIR, repo_dir)

    original_is_symlink = Path.is_symlink

    def fake_is_symlink(self):
        # Avoid calling self.resolve() here: pathlib's own resolve()
        # implementation may itself consult is_symlink() internally, and
        # since we're patching the class method, that would recurse through
        # our fake. Plain name/parent comparison sidesteps that.
        if self.name == "main.py" and self.parent == repo_dir:
            return True
        return original_is_symlink(self)

    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)

    result = walk_and_chunk(repo_dir, max_files=100)

    assert not any(c.file_path == "main.py" for c in result.chunks)
    assert result.files_processed == 2
    assert result.files_skipped == 1
    assert not any(f.path == "main.py" for f in result.files)


def test_is_likely_binary_detects_common_asset_extensions():
    assert _is_likely_binary(Path("logo.png"))
    assert _is_likely_binary(Path("assets/font.woff2"))
    assert _is_likely_binary(Path("clip.mp4"))
    assert _is_likely_binary(Path("archive.tar"))
    assert _is_likely_binary(Path("SOMETHING.PDF"))  # case-insensitive
    assert not _is_likely_binary(Path("main.py"))
    assert not _is_likely_binary(Path("README.md"))
    assert not _is_likely_binary(Path("no_extension"))


def test_walk_and_chunk_skips_binary_files_before_reading_them(tmp_path):
    repo_dir = tmp_path / "repo_with_binary"
    shutil.copytree(FIXTURE_DIR, repo_dir)

    # Bytes that would raise UnicodeDecodeError if actually read as UTF-8 --
    # proves the file is skipped by extension, not by falling through to the
    # existing UnicodeDecodeError handling.
    (repo_dir / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe\x00\x01binarydata")
    (repo_dir / "bundle.zip").write_bytes(b"PK\x03\x04\xff\xfe\x00\x01")

    result = walk_and_chunk(repo_dir, max_files=100)

    assert result.files_processed == 3  # only the 3 legitimate fixture files
    assert result.files_skipped == 2
    assert not any(f.path in ("logo.png", "bundle.zip") for f in result.files)
    assert not any(c.file_path in ("logo.png", "bundle.zip") for c in result.chunks)


@pytest.mark.slow
def test_ingest_local_directory_produces_embeddings():
    result = ingest_local_directory(FIXTURE_DIR, max_files=100)
    assert result.files_processed == 3
    assert len(result.chunks) > 0
    assert all(len(cwe.embedding) == 768 for cwe in result.chunks)
    assert len(result.files) == 3


def test_select_chunks_for_embedding_excludes_markdown_and_docs():
    chunks = [
        _chunk("main.py", "real code"),
        _chunk("README.md", "prose, not code"),
        _chunk("docs/guide.rst", "more prose"),
        _chunk("notes.txt", "plain text"),
    ]

    selected = select_chunks_for_embedding(chunks, max_files=15, max_chunks=1000)

    selected_paths = {c.file_path for c in selected}
    assert selected_paths == {"main.py"}


def test_select_chunks_for_embedding_caps_to_the_most_substantive_files():
    # 20 candidate files, each with one chunk whose size encodes its rank
    # (file 0 has the most content, file 19 the least) -- only the top 15 by
    # total chunked content should survive the cap. max_chunks set well
    # above 20 so it can't be the thing doing the capping here.
    chunks = [_chunk(f"file_{i}.py", content="x" * (200 - i)) for i in range(20)]

    selected = select_chunks_for_embedding(chunks, max_files=15, max_chunks=1000)

    selected_paths = {c.file_path for c in selected}
    assert len(selected_paths) == 15
    assert selected_paths == {f"file_{i}.py" for i in range(15)}
    assert "file_15.py" not in selected_paths
    assert "file_19.py" not in selected_paths


def test_select_chunks_for_embedding_keeps_all_chunks_of_a_selected_file():
    # A file contributing multiple chunks must have every one of them
    # survive the cap together -- the cap operates on files, not on
    # individual chunks within a kept file.
    chunks = [
        _chunk("big.py", "x" * 500),
        _chunk("big.py", "y" * 500),
        _chunk("big.py", "z" * 500),
        _chunk("small.py", "w"),
    ]

    selected = select_chunks_for_embedding(chunks, max_files=1, max_chunks=1000)

    assert len(selected) == 3
    assert all(c.file_path == "big.py" for c in selected)


def test_select_chunks_for_embedding_handles_empty_input():
    assert select_chunks_for_embedding([], max_files=15, max_chunks=40) == []


def test_select_chunks_for_embedding_caps_total_chunk_count_even_within_the_file_cap():
    # Regression test: a files-only cap isn't sufficient -- confirmed live,
    # a large real repo's top-15 files alone still carried hundreds of
    # chunks and kept embedding running 100+ seconds. Here, 3 files (well
    # under max_files=15) contribute 30 chunks each -- max_chunks=40 must
    # stop well before all 3 files' chunks are included.
    # Distinguishable total sizes so file ranking is deterministic: a.py has
    # the most content, then b.py, then c.py.
    chunks = (
        [_chunk("a.py", content="a" * 10) for _ in range(30)]
        + [_chunk("b.py", content="b" * 5) for _ in range(30)]
        + [_chunk("c.py", content="c" * 1) for _ in range(30)]
    )

    selected = select_chunks_for_embedding(chunks, max_files=15, max_chunks=40)

    assert len(selected) <= 40
    # Whole-file grouping: a.py (rank 1, 30 chunks) fits entirely under the
    # budget; b.py (rank 2, would add 30 more, blowing the 40 budget) must
    # be skipped entirely rather than truncated mid-file.
    selected_paths = {c.file_path for c in selected}
    assert selected_paths == {"a.py"}
    assert len(selected) == 30


def test_select_chunks_for_embedding_caps_a_single_oversized_file_rather_than_embedding_nothing():
    # Even the single largest (only) file alone exceeds max_chunks -- still
    # embed a bounded prefix of it rather than returning nothing at all.
    chunks = [_chunk("huge.py", content=f"chunk{i}") for i in range(100)]

    selected = select_chunks_for_embedding(chunks, max_files=15, max_chunks=40)

    assert len(selected) == 40
    assert all(c.file_path == "huge.py" for c in selected)
