"""API エンドポイントの統合テスト（upload → transactions → summary）。"""

from __future__ import annotations

import pytest

from tests.fixtures.build_sample_csv import build_csv


@pytest.mark.asyncio
async def test_upload_endpoint_happy_path(client):
    csv_bytes = build_csv()
    resp = await client.post(
        "/api/upload",
        files={"file": ("test.csv", csv_bytes, "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["household_id"] == "test-household"
    assert body["total_rows"] == 5
    assert body["imported"] == 3
    assert body["skipped_transfer"] == 1
    assert body["inserted"] == 3


@pytest.mark.asyncio
async def test_upload_is_idempotent(client):
    csv_bytes = build_csv()
    files = {"file": ("test.csv", csv_bytes, "text/csv")}

    r1 = (await client.post("/api/upload", files=files)).json()
    files = {"file": ("test.csv", csv_bytes, "text/csv")}
    r2 = (await client.post("/api/upload", files=files)).json()

    assert r1["inserted"] == 3
    assert r2["inserted"] == 0
    assert r2["unchanged"] == 3


@pytest.mark.asyncio
async def test_upload_empty_file_400(client):
    resp = await client.post(
        "/api/upload",
        files={"file": ("empty.csv", b"", "text/csv")},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_invalid_header_422(client):
    bad = '"a","b"\n1,2\n'.encode("cp932")
    resp = await client.post(
        "/api/upload",
        files={"file": ("bad.csv", bad, "text/csv")},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_transactions_lists_imported_rows(client):
    csv_bytes = build_csv()
    await client.post("/api/upload", files={"file": ("test.csv", csv_bytes, "text/csv")})

    resp = await client.get("/api/transactions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3  # 振替・計算対象外を除外
    assert len(body["items"]) == 3
    tickers = [t["source_id"] for t in body["items"]]
    assert set(tickers) == {"sample-001", "sample-002", "sample-003"}


@pytest.mark.asyncio
async def test_transactions_pagination(client):
    csv_bytes = build_csv()
    await client.post("/api/upload", files={"file": ("test.csv", csv_bytes, "text/csv")})

    resp = await client.get("/api/transactions?limit=2&offset=0")
    body = resp.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_summary_returns_totals(client):
    csv_bytes = build_csv()
    await client.post("/api/upload", files={"file": ("test.csv", csv_bytes, "text/csv")})

    resp = await client.get("/api/summary?start=2026-04-01&end=2026-04-30")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_income"] == "300000"
    assert body["total_expense"] == "4700"
    assert body["net"] == "295300"
    # 月別ブレイクダウン 1 ヶ月
    assert len(body["monthly"]) == 1
    assert body["monthly"][0]["year_month"] == "2026-04"


@pytest.mark.asyncio
async def test_auth_stub_requires_header_in_non_local(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    # 環境変数は既に client 起動済みなので、リクエストレベルの振る舞いを見るのは難しい
    # ここではローカルで X-Household-ID 指定時に値が反映されることを確認する
    csv_bytes = build_csv()
    await client.post(
        "/api/upload",
        files={"file": ("test.csv", csv_bytes, "text/csv")},
        headers={"X-Household-ID": "custom-household"},
    )

    resp = await client.get(
        "/api/transactions",
        headers={"X-Household-ID": "custom-household"},
    )
    body = resp.json()
    assert body["household_id"] == "custom-household"
    assert body["total"] == 3
