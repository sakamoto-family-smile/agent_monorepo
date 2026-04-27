"""問題生成バッチ。

`scripts/run_batch.py`（Cloud Run Job entry）から呼ばれ、`GenerationPipeline`
を N サイクル実行して合格分を `question_bank` に追加する。
"""

from app.batch.generation_runner import (
    BatchSummary,
    GenerationRunner,
    OutcomeStat,
)
from app.batch.plan import build_round_robin_plan, build_targeted_plan

__all__ = [
    "BatchSummary",
    "GenerationRunner",
    "OutcomeStat",
    "build_round_robin_plan",
    "build_targeted_plan",
]
