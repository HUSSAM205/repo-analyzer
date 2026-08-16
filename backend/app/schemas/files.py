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
