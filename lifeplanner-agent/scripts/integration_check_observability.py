"""分析基盤連携の実機検証スクリプト。

FastAPI lifespan を経由して setup_observability() を呼び、
代表的な API (シナリオ作成 / シミュレーション / チャット / CSV 取込) を
ASGI 経由で叩いて、`./data/_integration_check/raw/` に JSONL が
書き出されるかを最後に確認する。

使い方:
    cd lifeplanner-agent
    uv run python scripts/integration_check_observability.py

    # 実 LLM (Anthropic) を呼びたい場合は LLM_MOCK_MODE=false + ANTHROPIC_API_KEY を設定
    LLM_MOCK_MODE=false ANTHROPIC_API_KEY=sk-... uv run python scripts/integration_check_observability.py
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "app"))

# 出力先を分離 (.env 上書き)
_TEST_DATA_DIR = _ROOT / "data" / "_integration_check"
os.environ["ANALYTICS_DATA_DIR"] = str(_TEST_DATA_DIR)
os.environ.setdefault("ANALYTICS_ENABLED", "true")
os.environ.setdefault("ANALYTICS_SERVICE_NAME", "lifeplanner-agent-integration-check")
os.environ.setdefault("DEV_HOUSEHOLD_ID", "integration-check-household")
os.environ.setdefault("APP_ENV", "local")
# DB は一時 SQLite
os.environ["DB_URL"] = f"sqlite+aiosqlite:///{_TEST_DATA_DIR}/it.db"
# OTLP は使わなくても OK
os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "")
# LLM は MOCK が安全 (= 課金されない)。実呼出したい人は env で上書き。
os.environ.setdefault("LLM_MOCK_MODE", "true")


def _reset_test_dir() -> None:
    if _TEST_DATA_DIR.exists():
        shutil.rmtree(_TEST_DATA_DIR)
    _TEST_DATA_DIR.mkdir(parents=True)


def _scenario_payload() -> dict:
    return {
        "name": "IntegrationCheck",
        "description": "integration check",
        "primary_salary": "6000000",
        "spouse_salary": "3000000",
        "base_annual_expense": "4200000",
        "initial_net_worth": "5000000",
        "start_year": 2026,
        "horizon_years": 10,
        "salary_growth_rate": "0.01",
        "inflation_rate": "0.01",
        "investment_return_rate": "0.02",
    }


_CSV = (
    "計算対象,日付,内容,金額(円),保有金融機関,大項目,中項目,メモ,振替,ID\n"
    "1,2026/04/15,test,-1000,bank,食費,食料品,,0,id_x_1\n"
    "1,2026/04/16,test2,-2000,bank,住居,家賃,,0,id_x_2\n"
).replace("(円)", "（円）").encode("shift_jis")


async def _exercise(c) -> None:
    print("[integration] POST /api/scenarios")
    r = await c.post("/api/scenarios", json=_scenario_payload())
    r.raise_for_status()
    sid = r.json()["id"]
    print(f"  → scenario_id={sid}")

    print(f"[integration] POST /api/scenarios/{sid}/simulate")
    r = await c.post(f"/api/scenarios/{sid}/simulate")
    r.raise_for_status()

    print("[integration] POST /api/chat")
    r = await c.post("/api/chat", json={"scenario_ids": [sid], "question": "現状はどう?"})
    r.raise_for_status()

    print("[integration] POST /api/upload (small CSV)")
    files = {"file": ("test.csv", _CSV, "text/csv")}
    r = await c.post("/api/upload", files=files)
    r.raise_for_status()


def _verify() -> dict[str, int]:
    raw = _TEST_DATA_DIR / "raw"
    if not raw.exists():
        raise AssertionError(f"raw dir missing: {raw}")
    counts: dict[str, int] = {}
    for jsonl in sorted(raw.rglob("*.jsonl")):
        with jsonl.open() as f:
            for line in f:
                event = json.loads(line)
                et = event["event_type"]
                counts[et] = counts.get(et, 0) + 1
    return counts


async def main_async() -> int:
    _reset_test_dir()

    # config / db / instrumentation を fresh state で起動
    import importlib

    import config

    importlib.reload(config)
    from services import database as db_mod

    importlib.reload(db_mod)
    from services import llm_client as llm_mod

    importlib.reload(llm_mod)

    import instrumentation

    instrumentation.reset_for_tests()

    import main

    importlib.reload(main)

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as c:
        async with main.app.router.lifespan_context(main.app):
            try:
                await _exercise(c)
            except Exception as e:
                print(f"[integration] error during exercise: {type(e).__name__}: {e}")

    # lifespan exit 後に flush 済み
    counts = _verify()
    print()
    print("=" * 60)
    print(f"JSONL output dir: {_TEST_DATA_DIR}")
    print("event_type counts:")
    for et, n in sorted(counts.items()):
        print(f"  {et:24s}: {n}")
    print("=" * 60)

    expected = ["business_event"]  # 最低限
    missing = [et for et in expected if counts.get(et, 0) == 0]
    if missing:
        print(f"FAIL: required event types missing: {missing}")
        return 1

    biz_actions = set()
    for jsonl in (_TEST_DATA_DIR / "raw").rglob("event_type=business_event/**/*.jsonl"):
        with jsonl.open() as f:
            for line in f:
                ev = json.loads(line)
                biz_actions.add(ev["action"])

    print(f"business_event actions: {sorted(biz_actions)}")
    expected_actions = {"scenario_created", "scenario_simulated", "chat_completed", "csv_imported"}
    missing_actions = expected_actions - biz_actions
    if missing_actions:
        print(f"FAIL: missing business_event actions: {missing_actions}")
        return 1

    print("PASS: 主要 4 アクション (scenario_created / scenario_simulated / chat_completed / csv_imported) 確認")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
