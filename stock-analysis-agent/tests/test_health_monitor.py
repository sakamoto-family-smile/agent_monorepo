"""死活監視 (services.health_monitor / healthcheck_ping, PROPOSAL-0013) のテスト。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from services import health_monitor as hm
from services.healthcheck_ping import make_pinger

import config

NOW = datetime(2026, 11, 15, 12, tzinfo=UTC)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_freshness_check():
    assert hm.freshness_check("edinet:index", NOW, NOW - timedelta(hours=25)).ok
    stale = hm.freshness_check("edinet:index", NOW, NOW - timedelta(hours=30))
    assert not stale.ok
    assert stale.detail == "最終成功 30 時間前"
    assert hm.freshness_check("edinet:index", NOW, None).detail == "成功の記録なし"


def test_backup_check_uses_latest_file(tmp_path):
    (tmp_path / "stock_analysis-20261110-000000.db").write_bytes(b"")
    assert not hm.backup_check(NOW, tmp_path).ok

    (tmp_path / "stock_analysis-20261115-030000.db").write_bytes(b"")
    assert hm.backup_check(NOW, tmp_path).ok


def test_analysis_check():
    assert hm.analysis_check(2).ok
    assert not hm.analysis_check(3).ok


async def test_funnel_check_accepts_405_from_backend():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(405)

    async with _client(handler) as c:
        check = await hm.funnel_check("https://stock.example.ts.net", c)

    assert check.ok
    assert seen == ["https://stock.example.ts.net/api/line/webhook"]


async def test_funnel_check_fails_on_other_status_or_error():
    async with _client(lambda r: httpx.Response(502)) as c:
        assert (await hm.funnel_check("https://x.ts.net", c)).detail == "想定外の応答 HTTP 502"

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async with _client(boom) as c:
        check = await hm.funnel_check("https://x.ts.net", c)
    assert not check.ok
    assert "ConnectError" in check.detail


async def test_gateway_check_reads_liveliness():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200)

    async with _client(handler) as c:
        assert (await hm.gateway_check("http://litellm:4000", c)).ok
    assert seen == ["http://litellm:4000/health/liveliness"]

    async with _client(lambda r: httpx.Response(503)) as c:
        check = await hm.gateway_check("http://litellm:4000", c)
    assert not check.ok and check.detail == "想定外の応答 HTTP 503"


async def test_collect_checks_includes_gateway_when_configured(monkeypatch):
    monkeypatch.setattr(config.settings, "edinet_schedule_enabled", False)
    monkeypatch.setattr(config.settings, "backup_enabled", False)
    monkeypatch.setattr(config.settings, "public_base_url", "")
    monkeypatch.setattr(config.settings, "llm_gateway_url", "http://litellm:4000")

    async with _client(lambda r: httpx.Response(200)) as c:
        checks = await hm.collect_checks(
            now=NOW, last_success=lambda job: NOW, consecutive_failures=0, client=c
        )
    assert [c.key for c in checks] == ["llm-gateway", "analysis"]


async def test_collect_checks_only_includes_enabled_items(monkeypatch, tmp_path):
    monkeypatch.setattr(config.settings, "edinet_schedule_enabled", True)
    monkeypatch.setattr(config.settings, "backup_enabled", False)
    monkeypatch.setattr(config.settings, "public_base_url", "")
    monkeypatch.setattr(config.settings, "llm_gateway_url", "")

    async with _client(lambda r: httpx.Response(405)) as c:
        checks = await hm.collect_checks(
            now=NOW, last_success=lambda job: NOW, consecutive_failures=0, client=c
        )

    assert [c.key for c in checks] == ["edinet:index", "analysis"]
    assert all(c.ok for c in checks)


def test_transitions_notify_only_on_change():
    bad = hm.Check("funnel", False, "接続できません")
    good = hm.Check("funnel", True, "到達可能")
    ok_backup = hm.Check("backup", True, "最終成功 1 時間前")

    # 初回: 異常だけを知らせる (正常な項目は黙っている)
    assert hm.transitions({}, [bad, ok_backup]) == ([bad], [])
    # 異常が続いている間は知らせない
    assert hm.transitions({"funnel": False}, [bad]) == ([], [])
    # 復旧
    assert hm.transitions({"funnel": False}, [good]) == ([], [good])


async def test_monitor_sends_notice_on_failure_and_recovery():
    sent: list[str] = []

    async def notify(text: str) -> None:
        sent.append(text)

    monitor = hm.HealthMonitor(notify)
    bad = hm.Check("funnel", False, "接続できません (ConnectError)")
    good = hm.Check("funnel", True, "到達可能")

    await monitor.observe([good])
    await monitor.observe([bad])
    await monitor.observe([bad])
    await monitor.observe([good])

    assert len(sent) == 2
    assert "異常" in sent[0] and "funnel" in sent[0]
    assert "復旧" in sent[1]


async def test_monitor_survives_notify_failure():
    async def broken(text: str) -> None:
        raise RuntimeError("LINE down")

    await hm.HealthMonitor(broken).observe([hm.Check("funnel", False, "x")])


async def test_pinger_uses_stock_slug_and_fail_suffix():
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200)

    async with _client(handler) as c:
        ping = make_pinger("https://hc-ping.com/PINGKEY/", client=c)
        assert ping is not None
        await ping("backup", True)
        await ping("edinet_index", False)

    assert urls == [
        "https://hc-ping.com/PINGKEY/stock-backup?create=1",
        "https://hc-ping.com/PINGKEY/stock-edinet_index/fail?create=1",
    ]


async def test_pinger_does_not_log_url_on_error(caplog):
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    async with _client(boom) as c:
        ping = make_pinger("https://hc-ping.com/SECRETKEY", client=c)
        assert ping is not None
        await ping("health", True)

    assert "SECRETKEY" not in caplog.text
    assert "health" in caplog.text


def test_pinger_is_disabled_without_base():
    assert make_pinger("") is None
