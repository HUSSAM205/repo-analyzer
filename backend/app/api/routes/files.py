from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_repo_or_404
from app.core.code_annotation import (
    AnnotationUnavailableError,
    FileTooLargeForAnnotationError,
    generate_code_annotations,
)
from app.core.llm_providers import get_llm_client
from app.db.models import File, User
from app.db.session import get_db
from app.schemas.files import FileAnnotationsResponse, FileContentResponse, FileTreeEntry, FileTreeResponse

router = APIRouter(prefix="/api/v1/repos", tags=["files"])


def _build_tree(paths: list[str]) -> list[FileTreeEntry]:
    root: dict = {}
    for path in paths:
        parts = path.split("/")
        node = root
        for i, part in enumerate(parts):
            is_leaf = i == len(parts) - 1
            if part not in node:
                node[part] = {"__type__": "file" if is_leaf else "directory", "__children__": {}}
            node = node[part]["__children__"]

    def to_entries(tree: dict, prefix: str) -> list[FileTreeEntry]:
        entries = []
        for name in sorted(tree.keys()):
            info = tree[name]
            full_path = f"{prefix}/{name}" if prefix else name
            if info["__type__"] == "directory":
                entries.append(
                    FileTreeEntry(
                        name=name, path=full_path, type="directory",
                        children=to_entries(info["__children__"], full_path),
                    )
                )
            else:
                entries.append(FileTreeEntry(name=name, path=full_path, type="file", children=None))
        return entries

    return to_entries(root, "")


@router.get("/{repo_id}/files", response_model=FileTreeResponse)
async def get_file_tree(
    repo_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileTreeResponse:
    await get_repo_or_404(db, repo_id, current_user)
    result = await db.execute(select(File.path).where(File.repo_id == repo_id))
    paths = sorted(result.scalars().all())
    return FileTreeResponse(entries=_build_tree(paths))


@router.get("/{repo_id}/files/content", response_model=FileContentResponse)
async def get_file_content(
    repo_id: UUID,
    path: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileContentResponse:
    await get_repo_or_404(db, repo_id, current_user)
    result = await db.execute(select(File).where(File.repo_id == repo_id, File.path == path))
    file = result.scalar_one_or_none()
    if file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return FileContentResponse(path=file.path, content=file.content)


@router.get("/{repo_id}/files/annotations", response_model=FileAnnotationsResponse)
async def get_file_annotations(
    repo_id: UUID,
    path: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileAnnotationsResponse:
    await get_repo_or_404(db, repo_id, current_user)
    result = await db.execute(select(File).where(File.repo_id == repo_id, File.path == path))
    file = result.scalar_one_or_none()
    if file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    if file.annotations is not None:
        return FileAnnotationsResponse(path=file.path, blocks=file.annotations)

    try:
        blocks = await generate_code_annotations(file.content, file.path, get_llm_client())
    except FileTooLargeForAnnotationError as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    except AnnotationUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI annotation is currently unavailable for this file. Please try again.",
        ) from exc

    file.annotations = blocks
    await db.commit()
    return FileAnnotationsResponse(path=file.path, blocks=blocks)
