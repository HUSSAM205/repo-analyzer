import math

import pytest

from app.config import get_settings
from app.core.embeddings import embed_text, embed_texts

pytestmark = pytest.mark.slow


def test_embed_text_returns_correct_dimension():
    embedding = embed_text("def add(a, b): return a + b")
    assert len(embedding) == get_settings().embedding_dimension


def test_embed_texts_batch_matches_individual_count():
    texts = ["def foo(): pass", "class Bar: pass", "x = 1"]
    embeddings = embed_texts(texts)
    assert len(embeddings) == 3
    assert all(len(e) == get_settings().embedding_dimension for e in embeddings)


def test_embed_texts_empty_list_returns_empty():
    assert embed_texts([]) == []


def test_similar_code_has_higher_cosine_similarity_than_dissimilar():
    def cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        return dot / (norm_a * norm_b)

    e1 = embed_text("def add(a, b): return a + b")
    e2 = embed_text("def sum_values(x, y): return x + y")
    e3 = embed_text("class DatabaseConnection: pass")

    assert cosine(e1, e2) > cosine(e1, e3)
