import shutil
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

    chunks, processed, skipped = walk_and_chunk(repo_dir, max_files=100)

    # Only the three legitimate fixture files should be processed; the
    # symlink must be skipped, not read, not chunked.
    assert processed == 3
    assert skipped == 1
    assert not any("SUPER_SECRET_KEY_MATERIAL" in c.content for c in chunks)
    assert not any(c.file_path == "sneaky_link.py" for c in chunks)


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

    chunks, processed, skipped = walk_and_chunk(repo_dir, max_files=100)

    assert not any("outside content" in c.content for c in chunks)
    assert processed == 0


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

    chunks, processed, skipped = walk_and_chunk(repo_dir, max_files=100)

    assert not any(c.file_path == "main.py" for c in chunks)
    assert processed == 2
    assert skipped == 1


@pytest.mark.slow
def test_ingest_local_directory_produces_embeddings():
    result = ingest_local_directory(FIXTURE_DIR, max_files=100)
    assert result.files_processed == 3
    assert len(result.chunks) > 0
    assert all(len(cwe.embedding) == 768 for cwe in result.chunks)
