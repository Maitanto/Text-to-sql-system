from dataclasses import dataclass, field
from pathlib import Path

@dataclass(frozen=True)
class SandboxConfig:
    statement_timeout_ms: int = 2000
    max_rows: int = 500
    max_plan_cost: float = 100_000.0

@dataclass(frozen=True)
class PipelineConfig:
    seed: int = 42
    snapshot_date: str = "2026-11-21"
    float_tol: float = 1e-4
    data_dir: Path = Path("data/processed")
    predictions_dir: Path = Path("data/predictions")
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)

