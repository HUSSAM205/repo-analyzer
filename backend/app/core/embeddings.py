from functools import lru_cache

from app.config import get_settings

settings = get_settings()

# `torch`/`transformers` are deliberately NOT imported at module level.
# Confirmed live: every module that ever needs anything from this file
# (main.py's startup warm-up check, agent_tools.py, ingestion.py,
# search.py, workers/settings.py) gets imported unconditionally at process
# startup, regardless of Settings.enable_embedding -- a top-level `import
# torch` here meant this deployment's whole ~200-400MB torch/transformers
# footprint was being paid on every single boot, even in the exact
# configuration this app actually runs in production (ENABLE_EMBEDDING=
# false, see render.yaml), where embed_texts/_tokenizer/_model are never
# actually called at all. Deferring these imports into the functions that
# use them means that cost is now paid only if/when embedding genuinely
# runs -- zero baseline cost when it's disabled.
_threads_configured = False


def _ensure_thread_count_configured() -> None:
    # Must happen before any tensor ops run, and only once -- torch warns/
    # no-ops on a second call after its thread pools are already
    # initialized. Both the api and worker paths (now the same process,
    # see Settings.run_worker_in_process) import this module, so this
    # bounds both, not just the worker's heavier bulk embedding path.
    global _threads_configured
    if _threads_configured:
        return
    import torch

    torch.set_num_threads(settings.embedding_cpu_threads)
    _threads_configured = True


@lru_cache
def _tokenizer():
    # Configured before transformers is ever imported, not after -- torch
    # warns/no-ops on set_num_threads() once its thread pools are already
    # initialized, which transformers' own import can trigger as a side
    # effect (it imports torch internally). Same ordering the original
    # module-level code relied on, just deferred to first real use instead
    # of process startup.
    _ensure_thread_count_configured()
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(settings.embedding_model_name)


@lru_cache
def _model():
    _ensure_thread_count_configured()
    from transformers import AutoModel

    model = AutoModel.from_pretrained(settings.embedding_model_name)
    model.eval()
    return model


def embed_texts(texts: list[str], batch_size: int = 8) -> list[list[float]]:
    if not texts:
        return []

    import torch

    tokenizer = _tokenizer()
    model = _model()
    all_embeddings: list[list[float]] = []

    with torch.no_grad():
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            inputs = tokenizer(batch, padding=True, truncation=True, max_length=512, return_tensors="pt")
            outputs = model(**inputs)
            token_embeddings = outputs.last_hidden_state
            attention_mask = inputs["attention_mask"].unsqueeze(-1).expand(token_embeddings.size()).float()
            summed = torch.sum(token_embeddings * attention_mask, dim=1)
            counts = torch.clamp(attention_mask.sum(dim=1), min=1e-9)
            mean_pooled = summed / counts
            all_embeddings.extend(mean_pooled.tolist())

    return all_embeddings


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]
