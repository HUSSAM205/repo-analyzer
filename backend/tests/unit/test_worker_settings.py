import pytest

import app.workers.settings as worker_settings_module


@pytest.mark.asyncio
async def test_startup_warms_the_model_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr(worker_settings_module, "_tokenizer", lambda: calls.append("tokenizer"))
    monkeypatch.setattr(worker_settings_module, "_model", lambda: calls.append("model"))
    monkeypatch.setattr(worker_settings_module.settings, "warm_embedding_model_on_startup", True)

    await worker_settings_module.startup({})

    assert calls == ["tokenizer", "model"]


@pytest.mark.asyncio
async def test_startup_skips_warming_when_disabled(monkeypatch):
    # Confirmed live: both the api and worker processes eagerly loading
    # their own ~500MB CodeBERT copy at the same startup moment OOMs a
    # free-tier Render container capped at 512MB. This flag lets the
    # worker skip its copy -- the model still loads correctly on first
    # actual use (embed_texts calls the same lazily-cached functions), just
    # not eagerly at startup.
    calls = []
    monkeypatch.setattr(worker_settings_module, "_tokenizer", lambda: calls.append("tokenizer"))
    monkeypatch.setattr(worker_settings_module, "_model", lambda: calls.append("model"))
    monkeypatch.setattr(worker_settings_module.settings, "warm_embedding_model_on_startup", False)

    await worker_settings_module.startup({})

    assert calls == []


def test_poll_delay_is_tuned_down_from_arqs_default():
    # ARQ's own default (0.5s) polls Redis for new jobs continuously for the
    # entire lifetime of this in-process worker (see Settings.
    # run_worker_in_process), independent of real traffic -- live-confirmed
    # this alone is enough to exhaust a real Redis command quota. Must stay
    # meaningfully larger than the library default; the exact value can
    # change, but regressing back toward 0.5s would reintroduce the quota
    # burn this was tuned to fix.
    assert worker_settings_module.WorkerSettings.poll_delay >= 10
