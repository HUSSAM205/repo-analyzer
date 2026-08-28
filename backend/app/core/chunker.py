from dataclasses import dataclass

from app.core.ast_parser import language_for_path, parse_symbols

MAX_CHUNK_CHARS = 4000
FALLBACK_WINDOW_CHARS = 2000
FALLBACK_OVERLAP_CHARS = 200


@dataclass
class Chunk:
    file_path: str
    symbol_name: str | None
    node_type: str
    start_line: int
    end_line: int
    content: str


def chunk_file(file_path: str, source_code: str) -> list[Chunk]:
    if not source_code.strip():
        return []

    language = language_for_path(file_path)
    if language is not None:
        symbols = parse_symbols(source_code, language)
        if symbols:
            return [
                Chunk(
                    file_path=file_path,
                    symbol_name=symbol.name,
                    node_type=symbol.node_type,
                    start_line=symbol.start_line,
                    end_line=symbol.end_line,
                    content=symbol.content[:MAX_CHUNK_CHARS],
                )
                for symbol in symbols
            ]

    return _sliding_window_chunks(file_path, source_code)


def _sliding_window_chunks(file_path: str, source_code: str) -> list[Chunk]:
    lines = source_code.splitlines()
    if not lines:
        return []

    line_starts: list[int] = []
    running = 0
    for line in lines:
        line_starts.append(running)
        running += len(line) + 1

    full_text = "\n".join(lines)
    step_chars = FALLBACK_WINDOW_CHARS - FALLBACK_OVERLAP_CHARS

    chunks: list[Chunk] = []
    pos = 0
    while pos < len(full_text):
        window = full_text[pos:pos + FALLBACK_WINDOW_CHARS]
        chunks.append(
            Chunk(
                file_path=file_path,
                symbol_name=None,
                node_type="text",
                start_line=_line_for_offset(line_starts, pos),
                end_line=_line_for_offset(line_starts, pos + len(window)),
                content=window,
            )
        )
        if pos + FALLBACK_WINDOW_CHARS >= len(full_text):
            break
        pos += step_chars

    return chunks


def _line_for_offset(line_starts: list[int], offset: int) -> int:
    line = 1
    for i, start in enumerate(line_starts):
        if start <= offset:
            line = i + 1
        else:
            break
    return line
