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


class FileAnnotationsResponse(BaseModel):
    path: str
    blocks: list[CodeBlockAnnotation]
