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
