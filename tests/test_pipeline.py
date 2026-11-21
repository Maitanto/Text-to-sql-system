from decimal import Decimal
import pandas as pd
import pytest
from dataset_pipeline.eval_metrics import are_result_sets_equal, has_explicit_order_by
from dataset_pipeline.executor import check_single_readonly_statement
from dataset_pipeline.generator import assert_no_anchor_test_overlap
from dataset_pipeline.prepare_dataset import filter_test_leakage
from dataset_pipeline.prompts import extract_sql_from_response
from dataset_pipeline.schema_serializer import _normalize_constraint_def

def test_check_constraint_normalization_is_deterministic():
    raw = "CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'paid'::character varying])::text[])))"
    assert _normalize_constraint_def("c", raw) == "CHECK (status IN ('paid', 'pending'))"

def test_sql_extraction_handles_fences_and_rejects_pure_prose():
    assert extract_sql_from_response("Here is your query:\n```sql\nSELECT 1;\n```") == "SELECT 1;"
    assert extract_sql_from_response("I cannot answer that without more data.") is None

def test_sandbox_guardrail_blocks_stacked_or_mutating_queries():
    assert check_single_readonly_statement("SELECT * FROM orders;")[0] is True
    assert check_single_readonly_statement("SELECT 1; DROP TABLE orders;")[0] is False
    assert check_single_readonly_statement("DELETE FROM orders")[0] is False

def test_result_set_comparison_rules():
    # Multiset: duplicate rows must match in multiplicity
    assert are_result_sets_equal([(1,), (1,), (2,)], [(2,), (1,), (1,)], enforce_row_order=False) is True
    assert are_result_sets_equal([(1,), (1,)], [(1,)], enforce_row_order=False) is False
    # Ordered queries enforce exact sequence
    assert are_result_sets_equal([(1,), (2,)], [(2,), (1,)], enforce_row_order=True) is False
    assert has_explicit_order_by("SELECT id FROM users ORDER BY created_at DESC LIMIT 5") is True
    # NULL vs 0 and Decimal vs float tolerance
    assert are_result_sets_equal([(None,)], [(0,)]) is False
    assert are_result_sets_equal([(Decimal("10.00001"),)], [(10.0,)], float_tol=1e-4) is True

def test_leakage_guards_catch_anchor_and_dataset_overlap():
    test_pairs = [("Total revenue?", "SELECT SUM(amount) FROM orders;")]
    with pytest.raises(ValueError):
        assert_no_anchor_test_overlap(test_pairs, test_pairs)
    df = pd.DataFrame(
        [
            {"db_name": "sales", "question": "Total revenue?", "sql": "select sum(amount) from orders", "source": "synthetic_llm"},
            {"db_name": "sales", "question": "Count orders", "sql": "SELECT COUNT(*) FROM orders;", "source": "synthetic_llm"},
        ]
    )
    filtered = filter_test_leakage(df, test_pairs)
    assert len(filtered) == 1
    assert filtered.iloc[0]["question"] == "Count orders"

if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))