"""分析基盤連携の実機検証スクリプト。

実 Claude Agent SDK + 実 yfinance を呼び、analytics-platform に JSONL が
書き出されるかを最後に検証する。

使い方:
    cd stock-analysis-agent
    uv run python scripts/integration_check_observability.py

要件:
    - .env に CLAUDE_CODE_OAUTH_TOKEN が設定されていること
    - ネットワーク到達 (yfinance + Claude API)
    - 5 〜 30 秒程度の実 LLM 呼出 (1 ticker のみ)

出力ディレクトリは `./data/_integration_check/` (gitignored)。実行のたびに毎回 reset。
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

# パス設定 (uv run 経由ならいらないが、念のため)
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "app"))

# 出力先を分離 (.env を上書きするため早めに設定)
_TEST_DATA_DIR = _ROOT / "data" / "_integration_check"
os.environ["ANALYTICS_DATA_DIR"] = str(_TEST_DATA_DIR)
os.environ.setdefault("ANALYTICS_ENABLED", "true")
os.environ.setdefault("ANALYTICS_SERVICE_NAME", "stock-analysis-agent-integration-check")
# OTel エンドポイントは未設定で OK (Phoenix 起動していなくても問題なし)

# その後で import (config が env を読む)
import instrumentation  # noqa: E402
from agents.orchestrator import run_analysis  # noqa: E402
from models.stock import AnalysisRequest  # noqa: E402


def _reset_test_dir() -> None:
    if _TEST_DATA_DIR.exists():
        shutil.rmtree(_TEST_DATA_DIR)
    _TEST_DATA_DIR.mkdir(parents=True)


async def _run_real_analysis(query: str) -> None:
    request = AnalysisRequest(
        query=query,
        period="1mo",
        analysis_types=["technical"],
    )
    print(f"[integration] running analysis for query={query!r} ...")
    started = time.monotonic()
    n_events = 0
    async for ev in run_analysis(request):
        n_events += 1
        if ev.get("type") in ("ResultMessage", "report_complete"):
            print(f"[integration] received: {ev.get('type')}")
        if n_events > 200:
            print("[integration] received >200 SDK messages, stopping early")
            break
    elapsed = time.monotonic() - started
    print(f"[integration] orchestrator done in {elapsed:.1f}s ({n_events} SDK messages)")


def _verify_jsonl_output() -> dict[str, int]:
    raw = _TEST_DATA_DIR / "raw"
    if not raw.exists():
        raise AssertionError(f"raw dir does not exist: {raw}")

    counts: dict[str, int] = {}
    for jsonl in sorted(raw.rglob("*.jsonl")):
        with jsonl.open() as f:
            for line in f:
                event = json.loads(line)
                et = event["event_type"]
                counts[et] = counts.get(et, 0) + 1
    return counts


async def main() -> int:
    _reset_test_dir()

    instrumentation.setup_observability()
    try:
        await _run_real_analysis("Apple")
    except Exception as e:
        print(f"[integration] orchestrator raised: {type(e).__name__}: {e}")
    finally:
        await instrumentation.shutdown_observability()

    counts = _verify_jsonl_output()
    print()
    print("=" * 60)
    print(f"JSONL output dir: {_TEST_DATA_DIR}")
    print("event_type counts:")
    for et, n in sorted(counts.items()):
        print(f"  {et:24s}: {n}")
    print("=" * 60)

    expected_at_least = ["conversation_event", "business_event"]
    missing = [et for et in expected_at_least if counts.get(et, 0) == 0]
    if missing:
        print(f"FAIL: required event types missing: {missing}")
        return 1

    print("PASS: 基本イベント (conversation_event / business_event) を確認")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
