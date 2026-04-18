"""/api/networth の統合テスト。"""

from __future__ import annotations

from decimal import Decimal

import pytest

pytestmark = pytest.mark.asyncio


async def test_networth_empty(client):
    r = await client.get("/api/networth")
    assert r.status_code == 200
    body = r.json()
    assert body["total_assets"] == "0"
    assert body["total_liabilities"] == "0"
    assert body["net_worth"] == "0"


async def test_networth_with_assets_and_liabilities(client):
    # 資産 2 件
    await client.post(
        "/api/profile/assets",
        json={"kind": "deposit", "name": "A銀行", "value": "5000000", "as_of": "2026-04-01"},
    )
    await client.post(
        "/api/profile/assets",
        json={"kind": "investment", "name": "証券口座", "value": "3000000", "as_of": "2026-04-01"},
    )
    # 負債 1 件
    await client.post(
        "/api/profile/liabilities",
        json={
            "kind": "mortgage",
            "name": "住宅ローン",
            "balance": "25000000",
            "interest_rate": "0.0075",
            "as_of": "2026-04-01",
        },
    )

    r = await client.get("/api/networth")
    assert r.status_code == 200
    body = r.json()
    assert Decimal(body["total_assets"]) == Decimal("8000000")
    assert Decimal(body["total_liabilities"]) == Decimal("25000000")
    assert Decimal(body["net_worth"]) == Decimal("-17000000")
    assert body["by_kind_assets"]["deposit"] == "5000000"
    assert body["by_kind_assets"]["investment"] == "3000000"
    assert body["by_kind_liabilities"]["mortgage"] == "25000000"


async def test_networth_filters_by_as_of(client):
    """as_of より後の登録は集計に含まれない。"""
    await client.post(
        "/api/profile/assets",
        json={"kind": "cash", "name": "old", "value": "100000", "as_of": "2026-01-01"},
    )
    await client.post(
        "/api/profile/assets",
        json={"kind": "cash", "name": "future", "value": "999999", "as_of": "2027-01-01"},
    )
    r = await client.get("/api/networth?as_of=2026-04-01")
    body = r.json()
    assert Decimal(body["total_assets"]) == Decimal("100000")
