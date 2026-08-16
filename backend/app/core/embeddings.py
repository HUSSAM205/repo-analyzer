from functools import lru_cache

import torch
from transformers import AutoModel, AutoTokenizer

from app.config import get_settings

settings = get_settings()


@lru_cache
def _tokenizer():
    return AutoTokenizer.from_pretrained(settings.embedding_model_name)


@lru_cache
def _model():
    model = AutoModel.from_pretrained(settings.embedding_model_name)
    model.eval()
    return model


def embed_texts(texts: list[str], batch_size: int = 8) -> list[list[float]]:
    if not texts:
        return []

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
