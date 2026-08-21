import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete

from app.config import get_settings
from app.core.domain_briefing import generate_domain_briefing
from app.core.ingestion import (
    CloneError,
    RepoTooLargeError,
    clone_repo,
    embed_chunks,
    select_chunks_for_embedding,
    walk_and_chunk,
)
from app.core.llm_providers import get_llm_client
from app.db.models import CodeChunk, File, Job, JobStatus, NodeType, Repo, RepoStatus
from app.db.session import async_session_maker

settings = get_settings()


async def analyze_repo(ctx: dict, job_id: str) -> None:
    async with async_session_maker() as db:
        job = await db.get(Job, UUID(job_id))
        if job is None:
            return

        # repo is looked up here so it's in scope for the except blocks below,
        # but it's None until the try block actually sets it -- if db.get()
        # or the RUNNING commit itself raises (e.g. a transient DB blip),
        # the except blocks must still be able to tell there's no repo row
        # to mark FAILED yet (or find/mark it, once fetched) rather than
        # raising an uncaught NameError/AttributeError on top of the
        # original failure.
        repo = None

        try:
            repo = await db.get(Repo, job.repo_id)
            job.status = JobStatus.RUNNING
            job.stage = "cloning"
            job.started_at = datetime.now(timezone.utc)
            await db.commit()

            with tempfile.TemporaryDirectory() as tmp_dir:
                clone_path = await asyncio.to_thread(
                    clone_repo,
                    repo.url, Path(tmp_dir) / "repo",
                    max_size_mb=settings.max_repo_size_mb,
                    timeout_seconds=settings.clone_timeout_seconds,
                )

                job.stage = "parsing"
                await db.commit()

                walk_result = await asyncio.to_thread(
                    walk_and_chunk, clone_path, max_files=settings.max_files_per_repo
                )

                # Still within the "parsing" stage as far as the user is
                # concerned -- the AST/chunking walk and the domain briefing
                # LLM call are presented as one step. stream_chat() is an
                # async generator doing real async I/O (not a blocking
                # call), so it's awaited directly rather than routed through
                # asyncio.to_thread like the CPU-bound/blocking calls above.
                llm_client = get_llm_client()
                repo.domain_briefing = await generate_domain_briefing(walk_result, llm_client)

                # Re-analyzing an existing repo reuses the same Repo row with a
                # fresh Job (see POST /repos/analyze), so any files/chunks from
                # a previous analysis must be cleared before inserting the new
                # set, or every re-analysis doubles up. Deleting both here
                # (rather than only immediately before each is re-inserted)
                # keeps File and CodeChunk consistent with each other at every
                # commit point below, not just the final one.
                await db.execute(delete(CodeChunk).where(CodeChunk.repo_id == repo.id))
                await db.execute(delete(File).where(File.repo_id == repo.id))

                for walked_file in walk_result.files:
                    db.add(File(repo_id=repo.id, path=walked_file.path, content=walked_file.content))

                # Committed here -- before embedding starts, not after it
                # finishes. The file tree, code viewer, and domain briefing
                # card only ever needed File rows + repo.domain_briefing, never
                # CodeChunk embeddings, so gating all three behind the slowest
                # step (embedding) was an artificial dependency. Embeddings
                # power only chat's search_code tool, which read_file/
                # list_directory (app/core/agent_tools.py) already provide a
                # fallback for regardless of embedding coverage.
                job.progress = 60
                job.skipped_files = walk_result.files_skipped
                await db.commit()

                job.stage = "embedding"
                await db.commit()

                chunks_to_embed = select_chunks_for_embedding(walk_result.chunks, settings.embedding_max_files)
                embedded = await asyncio.to_thread(embed_chunks, chunks_to_embed)
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

                job.status = JobStatus.COMPLETED
                job.stage = "completed"
                job.progress = 100
                job.finished_at = datetime.now(timezone.utc)
                repo.status = RepoStatus.READY
                await db.commit()

        except (CloneError, RepoTooLargeError) as exc:
            await db.rollback()
            job.status = JobStatus.FAILED
            job.error_message = str(exc)
            job.finished_at = datetime.now(timezone.utc)
            if repo is not None:
                repo.status = RepoStatus.FAILED
            await db.commit()
        except asyncio.CancelledError:
            # ARQ's job_timeout (WorkerSettings) enforces its deadline by
            # cancelling this coroutine's task -- asyncio.CancelledError
            # inherits from BaseException, not Exception, so it is NOT
            # caught by `except Exception` below and would otherwise blow
            # straight past every status update in this function, leaving
            # the job/repo stuck at RUNNING forever (confirmed live: a
            # slow embedding step on a real repo hit exactly this path).
            # Mark both terminal FAILED here, then re-raise -- swallowing a
            # CancelledError without propagating it violates asyncio's
            # cancellation contract and can leave the task/event loop in an
            # inconsistent state.
            await db.rollback()
            job.status = JobStatus.FAILED
            job.error_message = "Analysis timed out"
            job.finished_at = datetime.now(timezone.utc)
            if repo is not None:
                repo.status = RepoStatus.FAILED
            await db.commit()
            raise
        except Exception as exc:
            await db.rollback()
            job.status = JobStatus.FAILED
            job.error_message = f"Unexpected error: {exc}"
            job.finished_at = datetime.now(timezone.utc)
            if repo is not None:
                repo.status = RepoStatus.FAILED
            await db.commit()
