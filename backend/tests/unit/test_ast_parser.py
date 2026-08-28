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
