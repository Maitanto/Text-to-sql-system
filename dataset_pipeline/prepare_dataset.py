import hashlib
import json
from pathlib import Path
import re
import pandas as pd
from dataset_pipeline.prompts import build_messages, build_user_prompt

try:
    import sqlglot
    from sqlglot import exp as sg_exp
except ImportError:
    sqlglot = None
    sg_exp = None

def canonicalize_sql(sql: str) -> str:
    """AST-normalized SQL string for exact duplicate and train/test leakage detection."""
    if sqlglot is not None:
        try:
            return sqlglot.transpile(sql, read="postgres", write="postgres", normalize=True)[0].lower()
        except Exception:
            pass
    return re.sub(r"\s+", " ", sql.strip().rstrip(";")).lower()

def extract_query_shape(sql: str) -> str:
    """
    Replaces literals and identifiers with placeholders to obtain the query's
    template family / structural fingerprint for leakage-resistant validation splitting.
    """
    if sqlglot is not None and sg_exp is not None:
        try:
            tree = sqlglot.parse_one(sql, read="postgres")
            for node in tree.walk():
                if isinstance(node, sg_exp.Literal):
                    node.replace(sg_exp.Placeholder())
                elif isinstance(node, sg_exp.Column):
                    node.set("this", sg_exp.Identifier(this="col"))
            return tree.sql(dialect="postgres").lower()
        except Exception:
            pass
    shape = re.sub(r"'[^']*'", "?", sql.lower())
    shape = re.sub(r"\b\d+(?:\.\d+)?\b", "?", shape)
    return re.sub(r"\s+", " ", shape).strip()

def filter_test_leakage(
    df: pd.DataFrame,
    test_pairs: list[tuple[str, str]],
) -> pd.DataFrame:
    """Removes any candidate whose canonical SQL or normalized question matches the held-out test set."""
    test_sql_canon = {canonicalize_sql(sql) for _, sql in test_pairs}
    test_questions = {re.sub(r"\s+", " ", q.strip().lower()) for q, _ in test_pairs}
    sql_match = df["sql"].map(canonicalize_sql).isin(test_sql_canon)
    q_match = df["question"].str.strip().str.lower().str.replace(r"\s+", " ", regex=True).isin(test_questions)
    return df[~(sql_match | q_match)].copy()

def load_and_deduplicate(jsonl_paths: list[Path]) -> pd.DataFrame:
    frames = [pd.read_json(p, lines=True) for p in jsonl_paths if p.exists()]
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["sql_canonical"] = df["sql"].map(canonicalize_sql)
    df["_priority"] = (df["source"] != "seed").astype(int)
    df = (
        df.sort_values("_priority")
        .drop_duplicates(subset=["db_name", "sql_canonical"], keep="first")
        .drop(columns=["sql_canonical", "_priority"])
        .reset_index(drop=True)
    )
    return df

def tag_sql_complexity(df: pd.DataFrame) -> pd.DataFrame:
    """Classifies structural difficulty (`simple`, `medium`, `hard`) from the SQL syntax."""
    def _classify(sql: str) -> str:
        upper = sql.upper()
        has_join = bool(re.search(r"\bJOIN\b", upper))
        has_agg = bool(re.search(r"\b(GROUP\s+BY|HAVING|COUNT|SUM|AVG|MIN|MAX)\b", upper))
        has_cte_or_sub = bool(re.search(r"(\bWITH\b|\(\s*SELECT\b)", upper))
        has_window_or_date = bool(re.search(r"\b(OVER\s*\(|INTERVAL|EXTRACT|DATE_TRUNC)\b", upper))
        score = int(has_join) + int(has_agg) + 2 * int(has_cte_or_sub) + int(has_window_or_date)
        if score >= 3:
            return "hard"
        if score >= 1:
            return "medium"
        return "simple"
    out = df.copy()
    out["complexity_tier"] = out["sql"].map(_classify)
    return out


def attach_model_agnostic_fields(df: pd.DataFrame) -> pd.DataFrame:
    """
    Stores model-agnostic chat messages and prompt/completion strings.
    Model-specific chat templates and completion-only loss masking are applied in `train.py`.
    """
    out = df.copy()
    out["messages_json"] = [
        json.dumps(build_messages(schema, q), ensure_ascii=False)
        for schema, q in zip(out["schema_prompt"], out["question"])
    ]
    out["prompt_text"] = [
        build_user_prompt(schema, q)
        for schema, q in zip(out["schema_prompt"], out["question"])
    ]
    out["completion_text"] = out["sql"].str.strip()
    return out

def split_and_save_parquet(
    df: pd.DataFrame,
    heldout_dbs: list[str],
    output_dir: Path = Path("data/processed"),
    val_seen_frac: float = 0.15,
    seed: int = 42,
) -> dict[str, int]:
    """
    Splits without schema or template-family leakage:
      - `eval_heldout.parquet`: completely unseen databases
      - `val_seen.parquet` & `train.parquet`: grouped by query shape (`extract_query_shape`)
        on seen databases so validation tests generalization rather than template memorization.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    heldout_df = df[df["db_name"].isin(heldout_dbs)].reset_index(drop=True)
    seen_df = df[~df["db_name"].isin(heldout_dbs)].copy()

    def _is_val_shape(shape: str) -> bool:
        digest = hashlib.sha256(f"{seed}:{shape}".encode("utf-8")).hexdigest()
        bucket = int(digest[:8], 16) / 0xFFFFFFFF
        return bucket < val_seen_frac
    
    seen_df["_shape"] = seen_df["sql"].map(extract_query_shape)
    val_mask = seen_df["_shape"].map(_is_val_shape)
    val_seen_df = seen_df[val_mask].drop(columns=["_shape"]).reset_index(drop=True)
    train_df = seen_df[~val_mask].drop(columns=["_shape"]).reset_index(drop=True)
    heldout_df.to_parquet(output_dir / "eval_heldout.parquet", index=False)
    val_seen_df.to_parquet(output_dir / "val_seen.parquet", index=False)
    train_df.to_parquet(output_dir / "train.parquet", index=False)
    return {
        "train": len(train_df),
        "val_seen": len(val_seen_df),
        "eval_heldout": len(heldout_df),
    }