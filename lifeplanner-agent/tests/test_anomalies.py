"""異常値検出 (services.anomalies + /api/anomalies) のテスト。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from models.transaction import Transaction as DomainTransaction
from repositories.household import ensure_household
from repositories.transaction import upsert_transactions
from services.anomalies import detect_anomalies
from services.category_mapper import load_category_mapper


def _tx(source_id: str, *, d: str, amount: int, category: str) -> DomainTransaction:
    y, m, dd = d.split("-")
    canonical = load_category_mapper().resolve(category)
    return DomainTransaction(
        source_id=source_id,
        date=date(int(y), int(m), int(dd)),
        content="x",
        amount=Decimal(amount),
        account="銀行A",
        category=category,
        subcategory=None,
        canonical_category=canonical.canonical,
        expense_type=canonical.expense_type,
        memo=None,
        is_transfer=False,
        is_target=True,
    )


@pytest.mark.asyncio
async def test_no_anomaly_when_history_stable(db_session):
    """過去 6 ヶ月の食費が安定していて、今月も同水準なら異常なし。"""
    hh = "anom-stable"
    await ensure_household(db_session, hh)
    rows = []
    # 2025-11 〜 2026-04 で毎月 3 万
    months = [("2025-11", 30_000), ("2025-12", 30_000), ("2026-01", 30_000),
              ("2026-02", 30_000), ("2026-03", 30_000), ("2026-04", 31_000)]
    for idx, (ym, amt) in enumerate(months):
        y, m = ym.split("-")
        rows.append(_tx(f"x{idx}", d=f"{y}-{m}-15", amount=-amt, category="食費"))
    await upsert_transactions(db_session, hh, rows)
    await db_session.commit()

    anomalies = await detect_anomalies(
        db_session, hh, target_month=date(2026, 4, 1), history_months=6
    )
    assert anomalies == []


@pytest.mark.asyncio
async def test_detects_3sigma_spike(db_session):
    """過去 6 ヶ月 平均 3 万 の食費が、対象月に 20 万に跳ねると異常検出される。"""
    hh = "anom-spike"
    await ensure_household(db_session, hh)
    rows = []
    # 履歴: 2025-10 ~ 2026-03 に各月 3 万
    history = [("2025-10", 30_000), ("2025-11", 30_000), ("2025-12", 30_000),
               ("2026-01", 30_000), ("2026-02", 30_000), ("2026-03", 30_000)]
    for idx, (ym, amt) in enumerate(history):
        y, m = ym.split("-")
        rows.append(_tx(f"h{idx}", d=f"{y}-{m}-15", amount=-amt, category="食費"))
    # 対象月 2026-04 に 20 万
    rows.append(_tx("spike", d="2026-04-10", amount=-200_000, category="食費"))
    await upsert_transactions(db_session, hh, rows)
    await db_session.commit()

    anomalies = await detect_anomalies(
        db_session, hh, target_month=date(2026, 4, 1), history_months=6, k=Decimal(3)
    )
    assert len(anomalies) == 1
    a = anomalies[0]
    assert a.canonical_category == "food"
    assert a.expense == Decimal(200_000)
    assert a.z_score > Decimal(3)


@pytest.mark.asyncio
async def test_no_anomaly_when_history_too_short(db_session):
    """履歴が min_samples (3) 未満のカテゴリは判定スキップ。"""
    hh = "anom-short"
    await ensure_household(db_session, hh)
    rows = [
        _tx("h1", d="2026-03-15", amount=-30_000, category="食費"),
        _tx("t", d="2026-04-10", amount=-500_000, category="食費"),
    ]
    await upsert_transactions(db_session, hh, rows)
    await db_session.commit()
    anomalies = await detect_anomalies(
        db_session, hh, target_month=date(2026, 4, 1), history_months=6, min_samples=3
    )
    assert anomalies == []


@pytest.mark.asyncio
async def test_anomalies_endpoint(client):
    """API エンドポイントが 200 を返す(異常なし)。"""
    r = await client.get("/api/anomalies?target_month=2026-04-01")
    assert r.status_code == 200
    body = r.json()
    assert body["target_month"] == "2026-04-01"
    assert body["anomalies"] == []
    assert body["history_months"] == 6


@pytest.mark.asyncio
async def test_anomalies_endpoint_validates_k(client):
    """k が範囲外(0.5)だと 422。"""
    r = await client.get("/api/anomalies?k=0.5")
    assert r.status_code == 422
