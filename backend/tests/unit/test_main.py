import asyncio

import pytest

import app.main as main_module
from app.main import lifespan, parse_cors_origins


def test_parse_cors_origins_empty_string_yields_no_origins():
    origins, allow_all = parse_cors_origins("")
    assert origins == []
    assert allow_all is False


def test_parse_cors_origins_splits_and_trims_a_comma_separated_list():
    origins, allow_all = parse_cors_origins(" https://a.example.com ,https://b.example.com,")
    assert origins == ["https://a.example.com", "https://b.example.com"]
    assert allow_all is False


def test_parse_cors_origins_wildcard_sets_allow_all():
    origins, allow_all = parse_cors_origins("*")
    assert origins == ["*"]
    assert allow_all is True


def test_parse_cors_origins_wildcard_mixed_with_specific_origins_still_sets_allow_all():
    origins, allow_all = parse_cors_origins("https://a.example.com,*")
    assert origins == ["https://a.example.com", "*"]
    assert allow_all is True


@pytest.mark.asyncio
async def test_lifespan_skips_model_warmup_when_disabled(monkeypatch):
    # Confirmed live: both the api and worker processes eagerly loading
    # their own ~500MB CodeBERT copy at the same startup moment OOMs a
    # free-tier Render container capped at 512MB (backend/scripts/
    # start_unified.sh runs both in one container). This flag lets the api
    # process skip its copy too.
    calls = []
    monkeypatch.setattr(main_module, "_tokenizer", lambda: calls.append("tokenizer"))
    monkeypatch.setattr(main_module, "_model", lambda: calls.append("model"))
    monkeypatch.setattr(main_module.settings, "warm_embedding_model_on_startup", False)

    async with lifespan(main_module.app):
        pass

    assert calls == []


@pytest.mark.asyncio
async def test_lifespan_does_not_start_an_in_process_worker_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr(main_module, "create_worker", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(main_module.settings, "run_worker_in_process", False)

    async with lifespan(main_module.app):
        pass

    assert calls == []


@pytest.mark.asyncio
async def test_lifespan_runs_and_cleanly_shuts_down_an_in_process_worker_when_enabled(monkeypatch):
    # Confirmed live: two separate OS processes (api + arq), even with
    # eager model warm-up disabled, still each import their own copy of
    # torch/transformers/langchain/langgraph -- enough on its own to OOM a
    # free-tier 512MB container. Running the worker loop inside this
    # process's own event loop instead means only one copy of each ever
    # gets imported.
    events = []

    class FakeWorker:
        async def async_run(self):
            events.append("async_run started")
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                events.append("async_run cancelled")
                raise

        async def close(self):
            events.append("closed")

    fake_worker = FakeWorker()

    def fake_create_worker(settings_cls, **kwargs):
        assert settings_cls is main_module.WorkerSettings
        assert kwargs == {"handle_signals": False}
        return fake_worker

    monkeypatch.setattr(main_module, "create_worker", fake_create_worker)
    monkeypatch.setattr(main_module.settings, "run_worker_in_process", True)

    async with lifespan(main_module.app):
        # Let the worker task actually start running before shutdown.
        await asyncio.sleep(0)

    assert events == ["async_run started", "async_run cancelled", "closed"]
