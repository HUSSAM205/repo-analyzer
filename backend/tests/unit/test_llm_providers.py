from app.core.llm import Message, ToolCall
from app.core.llm_providers import _to_anthropic_messages, _to_openai_messages


def test_to_anthropic_messages_converts_user_and_assistant():
    messages = [
        Message(role="user", content="What does main do?"),
        Message(role="assistant", content="It's the entry point."),
    ]
    result = _to_anthropic_messages(messages)
    assert result == [
        {"role": "user", "content": "What does main do?"},
        {"role": "assistant", "content": "It's the entry point."},
    ]


def test_to_anthropic_messages_converts_tool_call_and_result():
    tool_call = ToolCall(id="call_1", name="search_code", arguments={"query": "main"})
    messages = [
        Message(role="assistant", content="", tool_calls=[tool_call]),
        Message(role="tool", content="found it", tool_call_id="call_1"),
    ]
    result = _to_anthropic_messages(messages)
    assert result[0]["role"] == "assistant"
    assert result[0]["content"][0]["type"] == "tool_use"
    assert result[0]["content"][0]["id"] == "call_1"
    assert result[1]["role"] == "user"
    assert result[1]["content"][0]["type"] == "tool_result"
    assert result[1]["content"][0]["tool_use_id"] == "call_1"


def test_to_openai_messages_converts_tool_call_and_result():
    tool_call = ToolCall(id="call_1", name="search_code", arguments={"query": "main"})
    messages = [
        Message(role="assistant", content="", tool_calls=[tool_call]),
        Message(role="tool", content="found it", tool_call_id="call_1"),
    ]
    result = _to_openai_messages(messages)
    assert result[0]["role"] == "assistant"
    assert result[0]["tool_calls"][0]["id"] == "call_1"
    assert result[0]["tool_calls"][0]["function"]["name"] == "search_code"
    assert result[1] == {"role": "tool", "tool_call_id": "call_1", "content": "found it"}
