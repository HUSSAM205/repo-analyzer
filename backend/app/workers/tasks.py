import asyncio
import gc
import logging
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
logger = logging.getLogger(__name__)

# File rows are inserted in batches, committing after each, rather than
# building all ~max_files_per_repo File ORM objects in memory and issuing
# one commit at the end -- on a 512MB instance, SQLAlchemy's unit-of-work
# session otherwise holds the *entire* batch's worth of pending objects
# (each a copy of that file's content, on top of the raw content already
# held by walk_result.files) simultaneously right up until that single
# commit. Batching bounds that second copy's peak size to one batch instead
# of the whole repo.
_FILE_INSERT_BATCH_SIZE = 200


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
                    walk_and_chunk,
                    clone_path,
                    max_files=settings.max_files_per_repo,
                    # AST chunks (chunk_file's tree-sitter parse) only ever
                    # feed the embedding step below -- computing them at all
                    # when embedding is disabled is wasted CPU and memory
                    # for a result nothing will read. See walk_and_chunk's
                    # own docstring.
                    skip_chunking=not settings.enable_embedding,
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

                # Batched (see _FILE_INSERT_BATCH_SIZE above) -- each
                # commit flushes and clears SQLAlchemy's pending-object
                # unit-of-work state, so the ORM-object copy of this
                # batch's content can actually be freed before the next
                # batch starts, rather than every File object for the whole
                # repo accumulating in memory until one final commit.
                for batch_start in range(0, len(walk_result.files), _FILE_INSERT_BATCH_SIZE):
                    batch = walk_result.files[batch_start : batch_start + _FILE_INSERT_BATCH_SIZE]
                    for walked_file in batch:
                        db.add(File(repo_id=repo.id, path=walked_file.path, content=walked_file.content))
                    await db.commit()

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

                # walk_result.files (the raw content list) has now been
                # fully consumed -- generate_domain_briefing already read it
                # above, and every File row is committed. Drop the
                # reference and collect explicitly rather than waiting for
                # the embedding step (if any) to get its turn at the 512MB
                # budget with this still-referenced alongside it.
                walk_result.files.clear()
                gc.collect()

                # Confirmed live: loading the real ~500MB CodeBERT model
                # here is what actually exceeds a free-tier 512MB
                # instance's memory (embedding_cpu_threads/
                # WARM_EMBEDDING_MODEL_ON_STARTUP alone weren't enough --
                # the job was silently killed mid-embedding). Settings.
                # enable_embedding=false skips this step entirely rather
                # than attempt it and crash; search_code is excluded from
                # chat's tools in that case too (see
                # app/api/routes/chat.py) since the index would just stay
                # empty. Everything else (files, domain briefing,
                # list_directory/read_file in chat) is unaffected.
                if settings.enable_embedding:
                    job.stage = "embedding"
                    await db.commit()

                    chunks_to_embed = select_chunks_for_embedding(
                        walk_result.chunks, settings.embedding_max_files, settings.embedding_max_chunks
                    )
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
                # Final sweep: return everything this run allocated (parse
                # trees, chunk lists, embedding tensors if that step ran)
                # back to the allocator before this worker picks up its
                # next job -- see WorkerSettings.max_jobs (app/workers/
                # settings.py), which lets several of these run
                # back-to-back in the same process.
                gc.collect()

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
            # Log the full exception (e.g. a SQLAlchemy/asyncpg error's
            # str() includes the entire generated SQL statement and every
            # bound parameter -- for a batch File insert, that's the raw
            # content of several files) server-side only. Confirmed live:
            # storing str(exc) directly in job.error_message, which the
            # frontend shows verbatim, leaked exactly that -- an internal
            # SQL dump containing real repo file contents -- to the user.
            # The job row keeps a short, generic message instead.
            logger.exception("Unexpected error analyzing job=%s: %s", job.id, exc)
            await db.rollback()
            job.status = JobStatus.FAILED
            job.error_message = f"Unexpected error: {type(exc).__name__}"
            job.finished_at = datetime.now(timezone.utc)
            if repo is not None:
                repo.status = RepoStatus.FAILED
            await db.commit()
