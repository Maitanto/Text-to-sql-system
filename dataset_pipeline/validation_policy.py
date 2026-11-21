import re
from typing import Callable
from dataset_pipeline.config import SandboxConfig
from dataset_pipeline.executor import execute_readonly
from dataset_pipeline.models import ValidationResult

_VOLATILE_FN_RE = re.compile(r"\b(RANDOM|CLOCK_TIMESTAMP|TIMEOFDAY|TXID_CURRENT)\s*\(", re.IGNORECASE)

def validate_training_candidate(
    conn,
    question: str,
    sql: str,
    sandbox_cfg: SandboxConfig | None = None,
    allow_empty: bool = False,
    agreement_fn: Callable[[str, str], str | None] | None = None,
) -> ValidationResult:
    """
    Dataset-quality policy built on top of `execute_readonly`:
      1. Executes in the read-only sandbox.
      2. Rejects empty results (when allow_empty=False) and all-NULL degenerate aggregates like [(None,)].
      3. Rejects volatile non-deterministic functions.
      4. Optionally runs an independent SQL generator `agreement_fn(schema, question) -> alt_sql`
         and verifies that both queries return identical rows.
    """
    exec_res = execute_readonly(conn, sql, cfg=sandbox_cfg)
    if not exec_res.success:
        return ValidationResult(
            is_valid=False,
            error_stage=exec_res.error_stage,
            error_message=exec_res.error_message,
            execution=exec_res,
        )
    if _VOLATILE_FN_RE.search(sql):
        return ValidationResult(
            is_valid=False,
            error_stage="nondeterministic",
            error_message="Query uses volatile function (e.g., RANDOM/CLOCK_TIMESTAMP).",
            execution=exec_res,
        )
    if not allow_empty and exec_res.row_count == 0:
        return ValidationResult(
            is_valid=False,
            error_stage="degenerate_result",
            error_message="Query returned 0 rows.",
            execution=exec_res,
        )
    if exec_res.row_count == 1 and all(cell is None for cell in exec_res.rows[0]):
        return ValidationResult(
            is_valid=False,
            error_stage="degenerate_result",
            error_message="Query returned a single row of all NULL values.",
            execution=exec_res,
        )
    if agreement_fn is not None:
        alt_sql = agreement_fn(question, sql)
        if not alt_sql:
            return ValidationResult(
                is_valid=False,
                error_stage="agreement_mismatch",
                error_message="Agreement verifier failed to produce SQL.",
                execution=exec_res,
            )
        alt_res = execute_readonly(conn, alt_sql, cfg=sandbox_cfg)
        if not alt_res.success or alt_res.rows != exec_res.rows:
            return ValidationResult(
                is_valid=False,
                error_stage="agreement_mismatch",
                error_message="Independent verification query produced different results.",
                execution=exec_res,
            )
    return ValidationResult(is_valid=True, execution=exec_res)