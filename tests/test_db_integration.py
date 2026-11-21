import os
import re
from pathlib import Path

import psycopg
import pytest

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from dataset_pipeline.config import SandboxConfig
from dataset_pipeline.schema_serializer import serialize_database_schema
from dataset_pipeline.validation_policy import validate_training_candidate

pytestmark = pytest.mark.integration

QUERIES_FILE = Path(__file__).resolve().parents[1] / "queries_for_training.sql"

_TX_TABLE_RE = re.compile(r"\b(?:from|join)\s+(?:public\.)?(customers|products|transactions)\b", re.IGNORECASE)
_SUB_TABLE_RE = re.compile(r"\b(?:from|join)\s+(?:public\.)?(users|plans|subscriptions|payments)\b", re.IGNORECASE)

def _infer_target_db(sql: str) -> str:
    has_tx = bool(_TX_TABLE_RE.search(sql))
    has_sub = bool(_SUB_TABLE_RE.search(sql))
    if has_tx and not has_sub:
        return "transactions"
    if has_sub and not has_tx:
        return "subscriptions"
    raise ValueError(f"Could not unambiguously infer target database for SQL:\n{sql}")

def _load_seed_cases() -> list[pytest.param]:
    if not QUERIES_FILE.exists():
        return []
    cases: list[pytest.param] = []
    comment_lines: list[str] = []
    sql_lines: list[str] = []
    for raw_line in QUERIES_FILE.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if not sql_lines:
                comment_lines.clear()
            continue
        if stripped.startswith("--") and not sql_lines:
            comment_lines.append(stripped.lstrip("-").strip())
            continue
        # Strip inline `--` comments before checking for statement-ending semicolon
        code_part = raw_line.split("--", 1)[0].rstrip()
        if not code_part.strip():
            continue
        sql_lines.append(code_part)
        if code_part.endswith(";"):
            sql = "\n".join(sql_lines).strip()
            question = " ".join(comment_lines).strip() or f"Seed query #{len(cases) + 1}"
            db_name = _infer_target_db(sql)
            short_label = f"{db_name}-{len(cases) + 1:02d}: {question[:55]}"
            cases.append(pytest.param(db_name, question, sql, id=short_label))
            comment_lines.clear()
            sql_lines.clear()
    return cases

SEED_CASES = _load_seed_cases()

def get_connection(db_name: str) -> psycopg.Connection:
    return psycopg.connect(
        dbname=db_name,
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5436"),
    )

@pytest.fixture(scope="module")
def db_conns():
    try:
        conns = {
            "transactions": get_connection("transactions"),
            "subscriptions": get_connection("subscriptions"),
        }
    except Exception as exc:
        pytest.skip(f"PostgreSQL not reachable on localhost:5436 ({exc})")
    yield conns
    for conn in conns.values():
        conn.close()

def test_seed_queries_discovered():
    assert QUERIES_FILE.exists(), f"Seed file not found at {QUERIES_FILE}"
    assert len(SEED_CASES) > 0, f"Found {QUERIES_FILE}, but parsed 0 semicolon-terminated queries"

@pytest.mark.parametrize(("db_name", "question", "sql"), SEED_CASES)
def test_all_seed_queries_valid(db_conns, db_name, question, sql):
    cfg = SandboxConfig(statement_timeout_ms=2000)
    result = validate_training_candidate(
        db_conns[db_name],
        question=question,
        sql=sql,
        sandbox_cfg=cfg,
        allow_empty=False,
    )
    assert result.is_valid, (
        f"[{db_name}] Seed query failed at '{result.error_stage}': {result.error_message}\n"
        f"Question: {question}\n"
        f"SQL:\n{sql}"
    )
    assert result.execution is not None and result.execution.row_count > 0

def test_schema_serializer_live(db_conns):
    tx_schema = serialize_database_schema(db_conns["transactions"])
    sub_schema = serialize_database_schema(db_conns["subscriptions"])
    tx_lower = tx_schema.lower()
    for expected in ("customers", "products", "transactions", "date_of_transaction"):
        assert expected in tx_lower, f"Missing '{expected}' in serialized transactions schema"
    sub_lower = sub_schema.lower()
    for expected in ("users", "plans", "subscriptions", "payments", "user_login", "plans_name"):
        assert expected in sub_lower, f"Missing '{expected}' in serialized subscriptions schema"
    assert "paid" in sub_lower
    assert "monthly" in sub_lower

@pytest.mark.parametrize(
    ("db_name", "bad_sql", "expected_stage"),
    [
        ("transactions", "DELETE FROM customers;", "guardrail"),
        ("subscriptions", "SELECT 1; DROP TABLE users;", "guardrail"),
        ("subscriptions", "SELECT pg_sleep(5);", "timeout"),
        ("subscriptions", "SELECT RANDOM();", "nondeterministic"),
    ],
)
def test_sandbox_blocks_unsafe_or_slow_queries(db_conns, db_name, bad_sql, expected_stage):
    cfg = SandboxConfig(statement_timeout_ms=1000)
    result = validate_training_candidate(
        db_conns[db_name],
        question="Test unsafe or invalid query",
        sql=bad_sql,
        sandbox_cfg=cfg,
        allow_empty=True,
    )
    assert not result.is_valid, f"Unsafe or invalid query unexpectedly passed: {bad_sql}"
    assert result.error_stage == expected_stage
    target_table = "customers" if db_name == "transactions" else "users"
    with db_conns[db_name].cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {target_table};")
        assert cur.fetchone()[0] > 0