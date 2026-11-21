import json
from pathlib import Path
import random
import re
from typing import Callable

DEFAULT_COVERAGE_MATRIX: dict[tuple[str, str], int] = {
    ("lookup_filter", "simple"): 5,
    ("aggregation_groupby", "medium"): 10,
    ("multi_table_join", "medium"): 10,
    ("date_cohort_math", "hard"): 10,
    ("cte_subquery_ranking", "hard"): 10,
}

def load_sql_pairs(sql_path: Path) -> list[tuple[str, str]]:
    """
    Parses `-- Question` + `SELECT ...;` blocks.
    Keep anchor files strictly separate from my 50 held-out test queries.
    """
    text = sql_path.read_text(encoding="utf-8")
    pairs: list[tuple[str, str]] = []
    current_question: list[str] = []
    current_sql: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("--"):
            if current_question and current_sql:
                pairs.append((" ".join(current_question), "\n".join(current_sql).strip()))
                current_question, current_sql = [], []
            current_question.append(line.lstrip("-").strip())
        else:
            current_sql.append(raw_line.rstrip())
            if line.endswith(";"):
                if current_question and current_sql:
                    pairs.append((" ".join(current_question), "\n".join(current_sql).strip()))
                current_question, current_sql = [], []
    if current_question and current_sql:
        pairs.append((" ".join(current_question), "\n".join(current_sql).strip()))
    return pairs

def assert_no_anchor_test_overlap(
    anchor_pairs: list[tuple[str, str]],
    test_pairs: list[tuple[str, str]],
) -> None:
    """Hard guardrail preventing few-shot anchor leakage from the evaluation benchmark."""
    test_questions = {q.strip().lower() for q, _ in test_pairs}
    test_sqls = {re.sub(r"\s+", " ", s.strip().lower()) for _, s in test_pairs}
    for q, s in anchor_pairs:
        if q.strip().lower() in test_questions or re.sub(r"\s+", " ", s.strip().lower()) in test_sqls:
            raise ValueError(f"Leakage detected: anchor query overlaps with test set: {q!r}")

def generate_template_candidates(schema_prompt: str) -> list[dict[str, str]]:
    """
    Deterministic template backend for reliable baseline labels on common SQL families
    (table row counts, null checks, top-N ordering).
    """
    table_names = re.findall(r"CREATE TABLE\s+([a-zA-Z0-9_]+)\s*\(", schema_prompt)
    candidates: list[dict[str, str]] = []
    for tbl in table_names:
        candidates.append(
            {
                "question": f"How many total records are in {tbl}?",
                "sql": f"SELECT COUNT(*) AS total_count FROM {tbl};",
                "category": "aggregation_groupby",
                "complexity_tier": "simple",
                "source": "synthetic_template",
            }
        )
    return candidates

def generate_llm_candidates_for_cell(
    schema_prompt: str,
    anchor_examples: list[tuple[str, str]],
    category: str,
    complexity_tier: str,
    num_candidates: int,
    llm_call_fn: Callable[[str], str],
    seed: int = 42,
) -> list[dict[str, str]]:
    """
    Generates synthetic (question, sql) candidates targeted to a specific
    `(category, complexity_tier)` cell in the coverage matrix.
    `llm_call_fn(prompt) -> str` wraps my chosen generator model (local 8B or API).
    """
    rng = random.Random(seed)
    few_shot = rng.sample(anchor_examples, k=min(3, len(anchor_examples))) if anchor_examples else []
    examples_block = "\n\n".join(
        f"Question: {q}\nSQL: {s}" for q, s in few_shot
    )
    prompt = (
        f"Generate {num_candidates} diverse, realistic PostgreSQL SELECT question-SQL pairs "
        f"for the schema below.\n"
        f"Target SQL pattern category: {category}\n"
        f"Target difficulty tier: {complexity_tier}\n"
        f"Rules:\n"
        f"- Use only tables, columns, and enum values present in the schema.\n"
        f"- Output a valid JSON array of objects: "
        f'[{{"question": "...", "sql": "..."}}].\n\n'
        f"### Schema\n{schema_prompt}\n\n"
        f"### Reference Style Examples (do not copy)\n{examples_block}"
    )
    raw_output = llm_call_fn(prompt)
    match = re.search(r"\[.*\]", raw_output, re.DOTALL)
    if not match:
        return []
    parsed = json.loads(match.group(0))
    results: list[dict[str, str]] = []
    for item in parsed:
        q = str(item.get("question", "")).strip()
        s = str(item.get("sql", "")).strip()
        if q and s:
            if not s.endswith(";"):
                s += ";"
            results.append(
                {
                    "question": q,
                    "sql": s,
                    "category": category,
                    "complexity_tier": complexity_tier,
                    "source": "synthetic_llm",
                }
            )
    return results