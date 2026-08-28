import json
import logging
import random

from app.core.llm import LLMClient, Message
from app.core.token_budget import MAX_CONTEXT_CHARS, sanitize_context
from app.db.models import File

logger = logging.getLogger(__name__)

_MAX_SAMPLE_FILES = 10
_MAX_FILE_CHARS = 3000
_QUESTION_COUNT = 3
_OPTIONS_PER_QUESTION = 4

_SKIP_SUFFIXES = (
    ".lock", ".min.js", ".min.css", ".map", ".svg", ".png", ".jpg", ".jpeg",
    ".gif", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".pdf", ".zip",
)
_SKIP_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "uv.lock", "poetry.lock"}

_SYSTEM_PROMPT = (
    "You are creating a short comprehension quiz to test whether someone has "
    "genuinely understood the architecture and key mechanics of this specific "
    "repository -- not generic programming trivia. Respond with strict JSON "
    "only -- no markdown code fences, no commentary, no text before or after "
    f"the JSON. The response must be a JSON array of exactly {_QUESTION_COUNT} "
    "objects, each with exactly these keys: \"question\" (a specific question "
    "about THIS repo's actual code, files, or architecture -- something only "
    "answerable by someone who read it), \"options\" (a JSON array of exactly "
    f"{_OPTIONS_PER_QUESTION} short, plausible answer strings -- avoid making "
    "the correct one obviously longer or more detailed than the others), "
    "\"correct_index\" (the 0-based index of the correct option), and "
    "\"explanation\" (1-2 sentences on why that answer is correct, citing the "
    "actual file or mechanism where relevant). Vary difficulty across the "
    "three questions -- one easy/orienting question about what the project "
    "is, one medium question about its structure, and one that requires "
    "genuinely understanding a specific mechanism you saw in the code."
)


def _is_scannable(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if name in _SKIP_NAMES:
        return False
    return not path.lower().endswith(_SKIP_SUFFIXES)


def _pick_sample_files(files: list[File]) -> list[File]:
    return [f for f in files if _is_scannable(f.path)][:_MAX_SAMPLE_FILES]


def _build_prompt(files: list[File]) -> str:
    parts = ["Repository files to base the quiz on:"]
    budget = MAX_CONTEXT_CHARS
    for f in _pick_sample_files(files):
        snippet = sanitize_context(f.content[:_MAX_FILE_CHARS])
        block = f"--- {f.path} ---\n{snippet}\n"
        if len(block) > budget:
            break
        parts.append(block)
        budget -= len(block)
    return "\n".join(parts)


def _parse_questions(text: str) -> list[dict] | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped[3:]
        if stripped[:4].lower() == "json":
            stripped = stripped[4:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()

    parsed = json.loads(stripped)
    if not isinstance(parsed, list):
        raise ValueError("LLM response was not a JSON array")

    questions: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        question = item.get("question")
        options = item.get("options")
        correct_index = item.get("correct_index")
        explanation = item.get("explanation")
        if not isinstance(question, str) or not question:
            continue
        if not isinstance(options, list) or len(options) != _OPTIONS_PER_QUESTION:
            continue
        if not all(isinstance(o, str) and o for o in options):
            continue
        if not isinstance(correct_index, int) or not (0 <= correct_index < _OPTIONS_PER_QUESTION):
            continue
        if not isinstance(explanation, str) or not explanation:
            continue
        questions.append({
            "question": question,
            "options": options,
            "correct_index": correct_index,
            "explanation": explanation,
        })

    # A quiz with fewer than the expected question count is a worse
    # experience than a clean "unavailable" state -- unlike
    # security_scanner's findings list (where a partial list is still
    # useful), there's no good reason to show a 1- or 2-question "quiz".
    if len(questions) < _QUESTION_COUNT:
        return None
    return questions[:_QUESTION_COUNT]


_EXTENSION_LANGUAGE = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".jsx": "JavaScript", ".go": "Go", ".java": "Java", ".rb": "Ruby", ".rs": "Rust",
    ".php": "PHP", ".c": "C", ".cpp": "C++", ".cs": "C#", ".kt": "Kotlin", ".swift": "Swift",
}
_DISTRACTOR_LANGUAGES = ["Python", "JavaScript", "Go", "Rust", "Java", "Ruby", "TypeScript"]
_TEST_PATH_HINTS = ("test", "spec", "__tests__")


def _shuffled_options(correct_answer: str, distractors: list[str]) -> tuple[list[str], int]:
    options = [correct_answer, *distractors]
    random.shuffle(options)
    return options, options.index(correct_answer)


def build_deterministic_quiz(files: list[File]) -> list[dict] | None:
    """A best-effort 3-question quiz using only cheap, deterministic
    file-tree signals -- no LLM call, so it's always available. Used as the
    fallback when generate_quiz's real, code-comprehension quiz can't be
    produced (provider exhausted/erroring), so a viewer gets a real (if
    shallower -- these are file-tree-fact questions, not "do you understand
    this code's logic" questions the way the AI version's are) quiz instead
    of a 503. Returns None only for a genuinely empty repo, since there's no
    file-tree fact left to ask about at all.
    """
    if not files:
        return None

    questions: list[dict] = []

    # Q1: primary language, by file-extension count (always answerable,
    # even for a repo with no recognized extension at all -- "Unknown" is
    # then a valid, correct answer among the distractors).
    ext_counts: dict[str, int] = {}
    for f in files:
        name = f.path.rsplit("/", 1)[-1]
        if "." in name:
            lang = _EXTENSION_LANGUAGE.get("." + name.rsplit(".", 1)[-1].lower())
            if lang:
                ext_counts[lang] = ext_counts.get(lang, 0) + 1
    primary_lang = max(ext_counts, key=ext_counts.get) if ext_counts else "Unknown"
    distractors = [lang for lang in _DISTRACTOR_LANGUAGES if lang != primary_lang][:3]
    while len(distractors) < 3:
        distractors.append("Assembly")
    options, correct_index = _shuffled_options(primary_lang, distractors)
    questions.append({
        "question": "What is the primary programming language used in this repository?",
        "options": options,
        "correct_index": correct_index,
        "explanation": f"Based on file extensions across the indexed files, {primary_lang} is the most common.",
    })

    # Q2: a real file path vs. plausible-looking fakes.
    real_paths = sorted({f.path for f in files})
    real_path = real_paths[len(real_paths) // 2]
    fake_options = [f"{real_path}.old", f"legacy/{real_path.rsplit('/', 1)[-1]}", "nonexistent_module.py"]
    options, correct_index = _shuffled_options(real_path, fake_options)
    questions.append({
        "question": "Which of these file paths actually exists in this repository?",
        "options": options,
        "correct_index": correct_index,
        "explanation": f"`{real_path}` is a real file in this repository's indexed file tree.",
    })

    # Q3: does it have automated tests?
    has_tests = any(hint in f.path.lower() for f in files for hint in _TEST_PATH_HINTS)
    correct_answer = "Yes, test-like files were detected" if has_tests else "No, no test-like files were detected"
    wrong_answer = "No, no test-like files were detected" if has_tests else "Yes, test-like files were detected"
    options, correct_index = _shuffled_options(
        correct_answer, [wrong_answer, "Cannot be determined from the file tree", "Only end-to-end tests, no unit tests"]
    )
    questions.append({
        "question": "Does this repository contain automated test files?",
        "options": options,
        "correct_index": correct_index,
        "explanation": (
            "Test-like paths (containing \"test\"/\"spec\"/\"__tests__\") were found in the repository."
            if has_tests else
            "No test-like paths were found anywhere in the repository's file tree."
        ),
    })

    return questions


async def generate_quiz(files: list[File], llm_client: LLMClient) -> list[dict] | None:
    """Generates a 3-question multiple-choice comprehension quiz for the repo.

    Returns None on any failure (LLM error, malformed/incomplete response)
    rather than raising, so the caller (see app/api/routes/flagship.py)
    surfaces a clean "temporarily unavailable" state and never caches a
    broken or incomplete quiz -- a later request can retry once the
    provider recovers.
    """
    if not files:
        return None

    prompt = _build_prompt(files)
    if not prompt.strip():
        return None

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

        return _parse_questions(accumulated)
    except Exception:
        logger.warning("Quiz generation failed", exc_info=True)
        return None
