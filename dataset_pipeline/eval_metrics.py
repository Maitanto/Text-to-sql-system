from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, time
from decimal import Decimal
import math
import re
from typing import Any
import pandas as pd
from dataset_pipeline.models import EvalRecord

try:
    import sqlglot
    from sqlglot import exp as sg_exp
except ImportError:
    sqlglot = None
    sg_exp = None

def has_explicit_order_by(sql: str) -> bool:
    """
    Detects whether the outer query specifies ORDER BY.
    Rule: compare row order strictly when the reference query is ordered.
    """
    if sqlglot is not None:
        try:
            tree = sqlglot.parse_one(sql, read="postgres")
            return tree.args.get("order") is not None
        except Exception:
            pass
    return bool(re.search(r"\bORDER\s+BY\b", sql, re.IGNORECASE))

def _normalize_scalar(val: Any) -> tuple[str, Any]:
    """
    Converts database driver values into canonical typed pairs so:
      - None stays distinct from 0, False, or ""
      - bool stays distinct from int (1 vs True)
      - Decimal and float share a numeric tag for tolerance comparison
      - date/datetime/time convert to ISO strings
    """
    if val is None:
        return ("null", None)
    if isinstance(val, bool):
        return ("bool", val)
    if isinstance(val, (int, float, Decimal)):
        return ("num", float(val))
    if isinstance(val, (datetime, date, time)):
        return ("dt", val.isoformat())
    return ("str", str(val).strip())

def _rows_match(
    row_a: tuple[tuple[str, Any], ...],
    row_b: tuple[tuple[str, Any], ...],
    float_tol: float,
) -> bool:
    if len(row_a) != len(row_b):
        return False
    for (tag_a, val_a), (tag_b, val_b) in zip(row_a, row_b):
        if tag_a != tag_b:
            return False
        if tag_a == "num":
            if math.isnan(val_a) and math.isnan(val_b):
                continue
            if not math.isclose(val_a, val_b, rel_tol=float_tol, abs_tol=float_tol):
                return False
        elif val_a != val_b:
            return False
    return True

def _row_sort_key(norm_row: tuple[tuple[str, Any], ...], float_tol: float) -> tuple:
    """Creates a hashable, sortable key for multiset matching with float quantization."""
    bucket_scale = round(1.0 / float_tol) if float_tol > 0 else 1_000_000
    key_parts = []
    for tag, val in norm_row:
        if tag == "null":
            key_parts.append((0, ""))
        elif tag == "num":
            key_parts.append((1, round(val * bucket_scale)))
        else:
            key_parts.append((2, str(val)))
    return tuple(key_parts)

def are_result_sets_equal(
    ref_rows: list[tuple[Any, ...]],
    pred_rows: list[tuple[Any, ...]],
    enforce_row_order: bool = False,
    float_tol: float = 1e-4,
) -> bool:
    """
    Documented comparison rules:
      1. Row count and column count must match (column aliases are ignored).
      2. Multiset semantics: duplicate rows matter (Counter / sorted multiset).
      3. Row order is enforced when `enforce_row_order=True`, ignored otherwise.
      4. Numeric values (int, float, Decimal) match within `float_tol`; NULLs match only NULLs.
    """
    if len(ref_rows) != len(pred_rows):
        return False
    if len(ref_rows) == 0:
        return True
    if len(ref_rows[0]) != len(pred_rows[0]):
        return False
    norm_ref = [tuple(_normalize_scalar(v) for v in r) for r in ref_rows]
    norm_pred = [tuple(_normalize_scalar(v) for v in r) for r in pred_rows]
    if enforce_row_order:
        return all(_rows_match(ra, rb, float_tol) for ra, rb in zip(norm_ref, norm_pred))
    sorted_ref = sorted(norm_ref, key=lambda r: _row_sort_key(r, float_tol))
    sorted_pred = sorted(norm_pred, key=lambda r: _row_sort_key(r, float_tol))
    return all(_rows_match(ra, rb, float_tol) for ra, rb in zip(sorted_ref, sorted_pred))

def build_eval_report(records: list[EvalRecord]) -> pd.DataFrame:
    """
    Aggregates per-example evaluation logs with explicit sample counts (`n`)
    and full failure taxonomy counts per split, database, category, and difficulty.
    """
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame([asdict(r) for r in records])
    stages = ["sql_extraction", "guardrail", "cost_exceeded", "timeout", "syntax_or_runtime", "wrong_rows"]
    grouped = (
        df.groupby(["split", "db_name", "category", "complexity_tier"], dropna=False)
        .agg(
            n=("is_exec_match", "count"),
            passed=("is_exec_match", "sum"),
            exec_accuracy=("is_exec_match", "mean"),
        )
        .reset_index()
    )
    for stage in stages:
        stage_counts = (
            df.assign(_hit=df["error_stage"] == stage)
            .groupby(["split", "db_name", "category", "complexity_tier"], dropna=False)["_hit"]
            .sum()
            .reset_index(name=f"err_{stage}")
        )
        grouped = grouped.merge(
            stage_counts,
            on=["split", "db_name", "category", "complexity_tier"],
            how="left",
        )
    grouped["exec_accuracy"] = grouped["exec_accuracy"].round(4)
    return grouped