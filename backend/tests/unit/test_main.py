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
