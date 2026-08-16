import uuid

from app.core.search import reciprocal_rank_fusion


def test_rrf_favors_items_ranked_high_in_both_lists():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fused = reciprocal_rank_fusion([a, b, c], [a, c, b])
    fused_ids = [item[0] for item in fused]
    assert fused_ids[0] == a


def test_rrf_includes_items_present_in_only_one_list():
    a, b = uuid.uuid4(), uuid.uuid4()
    fused = reciprocal_rank_fusion([a], [b])
    assert {item[0] for item in fused} == {a, b}


def test_rrf_empty_lists_returns_empty():
    assert reciprocal_rank_fusion([], []) == []
