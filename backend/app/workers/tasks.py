import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.config import get_settings
from app.core.ingestion import CloneError, RepoTooLargeError, clone_repo, embed_chunks, walk_and_chunk
from app.db.models import CodeChunk, Job, JobStatus, NodeType, Repo, RepoStatus
from app.db.session import async_session_maker

settings = get_settings()


async def analyze_repo(ctx: dict, job_id: str) -> None:
    async with async_session_maker() as db:
        job = await db.get(Job, UUID(job_id))
        if job is None:
            return

        repo = await db.get(Repo, job.repo_id)
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        await db.commit()

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                clone_path = clone_repo(
                    repo.url, Path(tmp_dir) / "repo",
                    max_size_mb=settings.max_repo_size_mb,
                    timeout_seconds=settings.clone_timeout_seconds,
                )
                chunks, _processed, skipped = walk_and_chunk(clone_path, max_files=settings.max_files_per_repo)
                job.progress = 50
                await db.commit()

                embedded = embed_chunks(chunks)
                job.progress = 90
                await db.commit()

                for item in embedded:
                    db.add(
                        CodeChunk(
                            repo_id=repo.id,
                            file_path=item.chunk.file_path,
                            symbol_name=item.chunk.symbol_name,
                            node_type=NodeType(item.chunk.node_type),
                            start_line=item.chunk.start_line,
                            end_line=item.chunk.end_line,
                            content=item.chunk.content,
                            embedding=item.embedding,
                        )
                    )

                job.skipped_files = skipped
                job.status = JobStatus.COMPLETED
                job.progress = 100
                job.finished_at = datetime.now(timezone.utc)
                repo.status = RepoStatus.READY
                await db.commit()

        except (CloneError, RepoTooLargeError) as exc:
            job.status = JobStatus.FAILED
            job.error_message = str(exc)
            job.finished_at = datetime.now(timezone.utc)
            repo.status = RepoStatus.FAILED
            await db.commit()
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error_message = f"Unexpected error: {exc}"
            job.finished_at = datetime.now(timezone.utc)
            repo.status = RepoStatus.FAILED
            await db.commit()
