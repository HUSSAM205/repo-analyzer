import pytest

from app.api.routes.chat import _is_chitchat


@pytest.mark.parametrize(
    "content",
    [
        "ok", "Ok", "OK!", "  ok  ",
        "okay", "kk", "k",
        "thanks", "Thanks!", "thank you", "thx", "ty",
        "got it", "understood", "makes sense", "sounds good",
        "no problem", "np",
        "waiting", "still waiting", "one sec", "hold on",
        "yes", "yeah", "no", "nope",
        "hi", "hello", "hey",
        "bye", "later",
    ],
)
def test_is_chitchat_matches_short_acknowledgments(content):
    assert _is_chitchat(content) is True


@pytest.mark.parametrize(
    "content",
    [
        "ok but what does auth.py do",
        "thanks, can you also check the login flow",
        "explain the repository architecture",
        "how does authentication work here",
        "hi, can you list the API routes",
        "",
        "   ",
    ],
)
def test_is_chitchat_does_not_match_real_questions(content):
    assert _is_chitchat(content) is False
