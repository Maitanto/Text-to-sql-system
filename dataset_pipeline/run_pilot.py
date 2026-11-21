from collections import Counter
from dataclasses import asdict
import pytest
import json
from pathlib import Path
from typing import Callable
from dataset_pipeline.config import PipelineConfig
from dataset_pipeline.generator import (
    DEFAULT_COVERAGE_MATRIX,
    assert_no_anchor_test_overlap,
    generate_llm_candidates_for_cell,
    generate_template_candidates,
    load_sql_pairs,
)
from dataset_pipeline.models import TrainingExample
from dataset_pipeline.schema_serializer import serialize_database_schema
from dataset_pipeline.validation_policy import validate_training_candidate

def run_pilot(
    db_connections: dict[str, tuple[object, Path]],
    test_sql_path: Path,
    llm_call_fn: Callable[[str], str] | None = None,
    cfg: PipelineConfig | None = None,
    output_path: Path = Path("data/pilot.jsonl"),
) -> None:
    """
    Audits anchor queries, generates targeted candidates across the coverage matrix,
    validates through the sandbox + policy layer, and logs survivorship counts.
    """
    cfg = cfg or PipelineConfig()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    test_pairs = load_sql_pairs(test_sql_path) if test_sql_path.exists() else []
    accepted: list[TrainingExample] = []
    attempted_by_cell: Counter[tuple[str, str]] = Counter()
    accepted_by_cell: Counter[tuple[str, str]] = Counter()
    for db_name, (conn, anchor_file) in db_connections.items():
        try:
            schema_prompt = serialize_database_schema(conn, include_sample_rows=True)
            anchors = load_sql_pairs(anchor_file)
            assert_no_anchor_test_overlap(anchors, test_pairs)
            for question, sql in anchors:
                res = validate_training_candidate(conn, question, sql, sandbox_cfg=cfg.sandbox)
                if res.is_valid:
                    accepted.append(
                        TrainingExample(db_name, schema_prompt, question, sql, source="seed")
                    )
                else:
                    print(f"[ANCHOR FAIL] {db_name} | {res.error_stage}: {res.error_message}")
            for item in generate_template_candidates(schema_prompt):
                cell = (item["category"], item["complexity_tier"])
                attempted_by_cell[cell] += 1
                res = validate_training_candidate(
                    conn, item["question"], item["sql"], sandbox_cfg=cfg.sandbox
                )
                if res.is_valid:
                    accepted_by_cell[cell] += 1
                    accepted.append(
                        TrainingExample(
                            db_name=db_name,
                            schema_prompt=schema_prompt,
                            question=item["question"],
                            sql=item["sql"],
                            source=item["source"],
                            category=item["category"],
                            complexity_tier=item["complexity_tier"],
                        )
                    )
            if llm_call_fn is not None:
                for (category, tier), target_count in DEFAULT_COVERAGE_MATRIX.items():
                    candidates = generate_llm_candidates_for_cell(
                        schema_prompt=schema_prompt,
                        anchor_examples=anchors,
                        category=category,
                        complexity_tier=tier,
                        num_candidates=target_count,
                        llm_call_fn=llm_call_fn,
                        seed=cfg.seed,
                    )
                    for item in candidates:
                        cell = (category, tier)
                        attempted_by_cell[cell] += 1
                        res = validate_training_candidate(
                            conn, item["question"], item["sql"], sandbox_cfg=cfg.sandbox
                        )
                        if res.is_valid:
                            accepted_by_cell[cell] += 1
                            accepted.append(
                                TrainingExample(
                                    db_name=db_name,
                                    schema_prompt=schema_prompt,
                                    question=item["question"],
                                    sql=item["sql"],
                                    source=item["source"],
                                    category=category,
                                    complexity_tier=tier,
                                )
                            )
        finally:
            conn.close()

    with output_path.open("w", encoding="utf-8") as f:
        for ex in accepted:
            f.write(json.dumps(asdict(ex), ensure_ascii=False) + "\n")
    print(f"Saved {len(accepted)} validated examples to {output_path}")
    for cell, attempted in sorted(attempted_by_cell.items()):
        kept = accepted_by_cell[cell]
        print(f"  {cell}: {kept}/{attempted} survived validation")

if __name__ == "__main__":
    import os
    from pathlib import Path
    import psycopg
    from dotenv import load_dotenv

    load_dotenv()

    def _connect(db_name: str) -> psycopg.Connection:
        return psycopg.connect(
            dbname=db_name,
            user=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD"),
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=os.getenv("POSTGRES_PORT", "5436"),
        )

    seed_path = Path("queries_for_training.sql")
    if not seed_path.exists():
        seed_path = Path("querries_for_training.sql")

    conns = {
        "transactions": (_connect("transactions"), seed_path),
        "subscriptions": (_connect("subscriptions"), seed_path),
    }
    try:
        run_pilot(
            db_connections=conns,
            test_sql_path=Path("queries_heldout.sql"),
            llm_call_fn=None,  # audits & exports validated anchor queries; plug in LLM callable for synthetic generation
        )
    finally:
        for conn, _ in conns.values():
            conn.close()