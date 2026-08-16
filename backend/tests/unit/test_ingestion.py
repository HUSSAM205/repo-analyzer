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
