import json
import re
import time
from dataset_pipeline.config import SandboxConfig
from dataset_pipeline.models import ExecutionResult

_COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)

def check_single_readonly_statement(sql: str) -> tuple[bool, str | None]:
    """
    Structural check ensuring a single SELECT/WITH statement (no stacked statements).
    Actual write protection is enforced by PostgreSQL `SET TRANSACTION READ ONLY` and DB role grants.
    """
    if not sql or not sql.strip():
        return False, "Empty SQL statement."
    stripped = _COMMENT_RE.sub(" ", sql).strip()
    if stripped.endswith(";"):
        stripped = stripped[:-1].strip()
    if ";" in stripped:
        return False, "Multiple SQL statements are not permitted."
    first_token = stripped.split(None, 1)[0].upper() if stripped else ""
    if first_token not in {"SELECT", "WITH"}:
        return False, f"Only SELECT or WITH queries are allowed, got '{first_token}'."
    return True, None

def execute_readonly(
    conn,
    sql: str,
    cfg: SandboxConfig | None = None,
) -> ExecutionResult:
    """
    Executes a SQL query inside a rolled-back, read-only transaction with:
      1. PostgreSQL read-only transaction + statement_timeout
      2. EXPLAIN cost pre-check to reject runaway Cartesian joins
      3. Row cap via fetchmany(max_rows + 1)
    Empty results (0 rows) return success=True; dataset policies belong in validation_policy.py.
    """
    cfg = cfg or SandboxConfig()
    is_ok, reason = check_single_readonly_statement(sql)
    if not is_ok:
        return ExecutionResult(success=False, error_stage="guardrail", error_message=reason)
    clean_sql = sql.strip().rstrip(";")
    start = time.perf_counter()
    try:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY;")
            cur.execute(f"SET LOCAL statement_timeout = {int(cfg.statement_timeout_ms)};")
            cur.execute(f"EXPLAIN (FORMAT JSON) {clean_sql}")
            plan_payload = cur.fetchone()[0]
            if isinstance(plan_payload, str):
                plan_payload = json.loads(plan_payload)
            total_cost = float(plan_payload[0]["Plan"]["Total Cost"])
            if total_cost > cfg.max_plan_cost:
                return ExecutionResult(
                    success=False,
                    error_stage="cost_exceeded",
                    error_message=f"Estimated plan cost {total_cost:.1f} exceeds cap {cfg.max_plan_cost:.1f}.",
                    elapsed_ms=(time.perf_counter() - start) * 1000,
                )
            cur.execute(clean_sql)
            columns = [desc[0] for desc in (cur.description or [])]
            fetched = cur.fetchmany(cfg.max_rows + 1)
            truncated = len(fetched) > cfg.max_rows
            rows = [tuple(r) for r in fetched[: cfg.max_rows]]
            return ExecutionResult(
                success=True,
                columns=columns,
                rows=rows,
                row_count=len(rows),
                truncated=truncated,
                elapsed_ms=(time.perf_counter() - start) * 1000,
            )
    except Exception as exc:
        sqlstate = getattr(exc, "sqlstate", None)
        stage = "timeout" if sqlstate == "57014" else "syntax_or_runtime"
        return ExecutionResult(
            success=False,
            error_stage=stage,
            error_message=str(exc).strip(),
            elapsed_ms=(time.perf_counter() - start) * 1000,
        )
    finally:
        conn.rollback()