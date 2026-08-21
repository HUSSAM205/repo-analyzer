"""Shared token-budget utilities for capping repository content sent to LLMs.

Provider per-minute token limits are hit fastest by large repository
content -- a full file via read_file, several search_code snippets, or a
whole file's worth of code blocks batched into one annotation prompt.
Confirmed live: a single annotation prompt for a ~1400-line file hit Groq's
"Request too large ... tokens per minute (TPM): Limit 8000, Requested
10426" 413 -- this budget exists to keep any one piece of repository
content comfortably under that kind of limit.

A rough, standard ~4-characters-per-token approximation is used throughout
(good enough to stay well clear of a limit measured in thousands of tokens;
not intended for precise accounting -- getting an exact tokenizer per
provider would be real complexity for no practical benefit here).
"""

MAX_CONTEXT_TOKENS = 4000
_CHARS_PER_TOKEN = 4
MAX_CONTEXT_CHARS = MAX_CONTEXT_TOKENS * _CHARS_PER_TOKEN


def sanitize_context(text: str) -> str:
    """Strip low-value filler before budgeting.

    Collapses runs of 2+ consecutive blank lines down to 1 and trims
    trailing whitespace from every line, so the token budget is spent on
    real content instead of formatting noise (common in generated/minified
    output and files with heavy vertical whitespace).
    """
    collapsed: list[str] = []
    blank_run = 0
    for line in text.splitlines():
        stripped = line.rstrip()
        if stripped == "":
            blank_run += 1
            if blank_run > 1:
                continue
        else:
            blank_run = 0
        collapsed.append(stripped)
    return "\n".join(collapsed)


def truncate_to_token_budget(text: str, max_tokens: int = MAX_CONTEXT_TOKENS) -> str:
    """Sanitize `text` and truncate it to roughly `max_tokens` tokens.

    Returns the text unchanged (aside from sanitizing) if it already fits.
    """
    sanitized = sanitize_context(text)
    max_chars = max_tokens * _CHARS_PER_TOKEN
    if len(sanitized) <= max_chars:
        return sanitized

    notice = f"\n... [truncated to stay within the {max_tokens}-token context budget]"
    # For a very small max_tokens, the notice itself can be longer than
    # max_chars -- clamp to 0 rather than let a negative slice index wrap
    # around and keep text from the *end* of `sanitized` instead of the
    # start.
    keep_chars = max(max_chars - len(notice), 0)
    return sanitized[:keep_chars] + notice
