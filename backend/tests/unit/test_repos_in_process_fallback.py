import asyncio

import pytest

from app.api.routes import repos as repos_module


@pytest.mark.asyncio
async def test_run_analysis_with_timeout_calls_analyze_repo(monkeypatch):
    calls = []

    async def fake_analyze_repo(ctx, job_id):
        calls.append((ctx, job_id))

    monkeypatch.setattr(repos_module, "analyze_repo", fake_analyze_repo)

    await repos_module._run_analysis_with_timeout("job-123")

    assert calls == [({}, "job-123")]


@pytest.mark.asyncio
async def test_run_analysis_with_timeout_swallows_a_timeout(monkeypatch):
    async def slow_analyze_repo(ctx, job_id):
        await asyncio.sleep(10)

    monkeypatch.setattr(repos_module, "analyze_repo", slow_analyze_repo)
    monkeypatch.setattr(repos_module, "_FALLBACK_JOB_TIMEOUT_SECONDS", 0.01)

    # Must not raise -- in production, analyze_repo's own
    # `except asyncio.CancelledError` handler is what marks the Job/Repo
    # FAILED when wait_for's timeout cancels it; this wrapper just must not
    # let the TimeoutError itself escape and become an unhandled task
    # exception.
    await repos_module._run_analysis_with_timeout("job-123")


@pytest.mark.asyncio
async def test_run_analysis_with_timeout_swallows_and_logs_unexpected_exceptions(monkeypatch, caplog):
    async def broken_analyze_repo(ctx, job_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(repos_module, "analyze_repo", broken_analyze_repo)

    # Must not raise -- this runs detached via asyncio.create_task with
    # nothing else positioned to observe a raised exception, so it has to
    # be swallowed (and logged) here instead of becoming a silent "Task
    # exception was never retrieved" warning.
    with caplog.at_level("ERROR"):
        await repos_module._run_analysis_with_timeout("job-123")

    assert "job-123" in caplog.text


@pytest.mark.asyncio
async def test_schedule_in_process_analysis_keeps_a_reference_until_done(monkeypatch):
    async def fake_run(job_id):
        pass

    monkeypatch.setattr(repos_module, "_run_analysis_with_timeout", fake_run)

    repos_module._schedule_in_process_analysis("job-xyz")

    assert len(repos_module._fallback_tasks) == 1
    task = next(iter(repos_module._fallback_tasks))

    await task

    assert task not in repos_module._fallback_tasks
