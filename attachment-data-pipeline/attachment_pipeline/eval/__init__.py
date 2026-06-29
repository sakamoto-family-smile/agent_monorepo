"""精度評価 (precision@coverage / hallucination / recall / 誤り捕捉率)。"""

from __future__ import annotations

from .metrics import Metrics, canonicalize, compute_metrics, gold_canonical

__all__ = ["Metrics", "canonicalize", "compute_metrics", "gold_canonical"]
