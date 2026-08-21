from typing import Literal

from pydantic import BaseModel


class FileTreeEntry(BaseModel):
    name: str
    path: str
    type: str  # "file" | "directory"
    children: list["FileTreeEntry"] | None = None


FileTreeEntry.model_rebuild()


class FileTreeResponse(BaseModel):
    entries: list[FileTreeEntry]


class FileContentResponse(BaseModel):
    path: str
    content: str


class CodeBlockAnnotation(BaseModel):
    category: Literal["imports", "config_state", "business_logic", "handlers_endpoints"]
    start_line: int
    end_line: int
    logic_summary: str
    flow: str
    tips: str
    # "heuristic" means this block's explanation was generated locally
    # (tree-sitter segmentation + a label, no LLM) because the AI provider
    # was unavailable -- lets the frontend show an honest "AI unavailable"
    # indicator instead of presenting it as a full AI analysis. Defaults to
    # "ai" so annotations cached before this field existed still validate.
    source: Literal["ai", "heuristic"] = "ai"


class FileAnnotationsResponse(BaseModel):
    path: str
    blocks: list[CodeBlockAnnotation]
