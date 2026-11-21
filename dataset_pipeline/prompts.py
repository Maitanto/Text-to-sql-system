import re

SYSTEM_PROMPT = (
    "You are an expert PostgreSQL assistant. Given a databse schema and a question, "
    "respond with only a valid PostgreSQL SELECT query and no explanation."
)

_CODE_BLOCK_RE = re.compile(r"```(?:sql|postgresql)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_LEADING_SQL_RE = re.compile(r"\b(WITH|SELECT)\b.*", re.IGNORECASE | re.DOTALL)

def build_user_prompt(schema_prompt: str, question: str) -> str:
    return (
        f"### Database Schema\n{schema_prompt.strip()}\n\n"
        f"### Question\n{question.strip()}"
    )

def build_messages(schema_prompt: str, question: str) -> list[dict[str, str]]:
    """Model-agnostic chat messages used identically in data prep, inference, and serving."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(schema_prompt, question)},
    ]

def extract_sql_from_response(raw_text: str) -> str | None:
    """
    Extracts a SQL statement from model output.
    Returns None if the model emitted prose without a recognizable SELECT/WITH query.
    """
    if not raw_text or not raw_text.strip():
        return None
    text = raw_text.strip()
    fence_match = _CODE_BLOCK_RE.search(text)
    if fence_match:
        text = fence_match.group(1).strip()
    sql_match = _LEADING_SQL_RE.search(text)
    if not sql_match:
        return None
    candidate = sql_match.group(0).strip()
    if ";" in candidate:
        candidate = candidate.split(";", 1)[0].strip() + ";"
    return candidate if candidate else None
