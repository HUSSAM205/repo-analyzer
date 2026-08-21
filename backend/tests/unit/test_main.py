from app.main import parse_cors_origins


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
