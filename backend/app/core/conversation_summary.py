import logging

from app.core.llm import LLMClient, Message
from app.core.token_budget import MAX_CONTEXT_CHARS, sanitize_context

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You maintain a running summary of an ongoing chat conversation between "
    "a user and an AI coding assistant discussing a specific repository. "
    "You will be given the existing summary (or told there isn't one yet) "
    "followed by the next batch of raw messages that just aged out of the "
    "assistant's active context window. Produce an updated summary that "
    "folds the new messages into the existing one. Keep it concise (well "
    "under 300 words) -- capture what the user is trying to accomplish, key "
    "facts/decisions/code the assistant already explained, and anything "
    "still open or unresolved. Do not include pleasantries or restate "
    "things word-for-word. Respond with the updated summary text only -- no "
    "preamble, no markdown headers, no commentary about what you're doing."
)

_NO_PRIOR_SUMMARY_NOTICE = "None yet -- this is the first summary update for this conversation."


def _format_message(message: Message) -> str:
    role = "User" if message.role == "user" else "Assistant"
    return f"{role}: {message.content}"


async def fold_into_summary(
    llm_client: LLMClient, existing_summary: str | None, new_messages: list[Message]
) -> str | None:
    """Returns an updated rolling summary that folds `new_messages` into `existing_summary`.

    This is what lets a conversation grow past the recent-messages window
    (see chat.py's ROLLING_WINDOW_MESSAGES) without either the agent losing
    all memory of everything older, or every turn's prompt growing with the
    conversation's total length -- each call only processes the bounded
    slice of messages that newly aged out since the last update, not the
    whole history, so cost stays flat regardless of how long the
    conversation has run (10, 100, or 10,000+ turns).

    Never raises: the caller runs this as a fire-and-forget background step
    after a chat turn's own response has already been sent (see chat.py's
    send_message), so a failure here must not surface to the user or affect
    that turn in any way. On failure, returns `existing_summary` unchanged
    (None if there wasn't one yet) -- the next turn's context simply doesn't
    improve this round, it does not get worse either.
    """
    if not new_messages:
        return existing_summary

    prior = existing_summary or _NO_PRIOR_SUMMARY_NOTICE
    transcript = sanitize_context("\n".join(_format_message(m) for m in new_messages))
    # Bounds a single summarization prompt even in the pathological case of
    # a long unsummarized backlog (e.g. this step failed repeatedly for a
    # while) -- same defensive pattern as every other LLM-prompt builder in
    # this codebase (see token_budget.py's docstring).
    if len(transcript) > MAX_CONTEXT_CHARS:
        transcript = transcript[:MAX_CONTEXT_CHARS] + "\n... [older messages in this batch truncated]"
    prompt = f"Existing summary:\n{prior}\n\nNew messages to fold in:\n{transcript}"

    try:
        accumulated = ""
        llm_error: str | None = None
        async for event in llm_client.stream_chat(
            [Message(role="user", content=prompt)], tools=[], system_prompt=_SYSTEM_PROMPT
        ):
            if event.type == "token":
                accumulated += event.token or ""
            elif event.type == "error":
                llm_error = event.error

        if llm_error is not None:
            raise RuntimeError(f"LLM provider returned an error: {llm_error}")

        updated = accumulated.strip()
        if not updated:
            raise ValueError("LLM returned an empty summary")
        return updated
    except Exception:
        logger.warning("Conversation summary update failed -- keeping the previous summary", exc_info=True)
        return existing_summary
