from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutionResult:
    success: bool
    columns: list[str] = field(default_factory=list)
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    error_stage: str | None = None
    error_message: str | None = None
    elapsed_ms: float = 0.0

@dataclass
class ValidationResult:
    is_valid: bool
    error_stage: str | None = None
    error_message: str | None = None
    execution: ExecutionResult | None = None


@dataclass
class TrainingExample:
    db_name: str
    schema_prompt: str
    question: str
    sql: str
    source: str
    category: str = "general"
    complexity_tier: str = "simple"

@dataclass
class EvalRecord:
    example_id: str
    db_name: str
    split: str
    category: str
    complexity_tier: str
    question: str
    ref_sql: str
    pred_raw: str
    pred_sql: str | None
    is_exec_match: bool
    error_stage: str | None = None
    error_message: str | None = None