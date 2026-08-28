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
