import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
os.environ.setdefault("DB_PATH", "/tmp/test_ticker.db")
os.environ.setdefault("DATA_DIR", "/tmp/test_stock_data")


@pytest.fixture(autouse=True)
async def init_db_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CHARTS_DIR", str(tmp_path / "charts"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("DICTIONARIES_DIR", str(tmp_path / "dictionaries"))

    import importlib
    import config as cfg
    importlib.reload(cfg)

    from services.database import init_db
    await init_db()


@pytest.mark.asyncio
async def test_resolve_ticker_by_regex():
    from agents.ticker_resolver import resolve_ticker
    result = await resolve_ticker("AAPL")
    assert result.ticker == "AAPL"
    assert result.source == "regex"
    assert result.confidence >= 0.9


@pytest.mark.asyncio
async def test_resolve_jp_ticker_by_regex():
    from agents.ticker_resolver import resolve_ticker
    result = await resolve_ticker("7203")
    assert result.ticker == "7203.T"
    assert result.source == "regex"


@pytest.mark.asyncio
async def test_resolve_jp_new_format_code_by_regex():
    """JPX 新形式コード (数字3桁+英字, 2024-) も日本株として .T を付与する (例: 285A=キオクシア)。"""
    from agents.ticker_resolver import resolve_ticker

    for code in ("285A", "130A", "160A"):
        result = await resolve_ticker(code)
        assert result.ticker == f"{code}.T", f"{code} should resolve to {code}.T"
        assert result.source == "regex"


@pytest.mark.asyncio
async def test_resolve_jp_new_format_code_lowercase():
    """小文字入力でも新形式コードを正規化する。"""
    from agents.ticker_resolver import resolve_ticker

    result = await resolve_ticker("285a")
    assert result.ticker == "285A.T"


@pytest.mark.asyncio
async def test_resolve_jp_new_format_code_with_suffix_kept():
    """既に .T 付きなら二重付与しない。"""
    from agents.ticker_resolver import resolve_ticker

    result = await resolve_ticker("285A.T")
    assert result.ticker == "285A.T"


@pytest.mark.asyncio
async def test_resolve_us_ticker_not_treated_as_jp():
    """英字始まりの US ティッカーには .T を付けない (誤判定防止)。"""
    from agents.ticker_resolver import resolve_ticker

    result = await resolve_ticker("AAPL")
    assert result.ticker == "AAPL"


@pytest.mark.asyncio
async def test_resolve_toyota_by_dict():
    from agents.ticker_resolver import resolve_ticker
    result = await resolve_ticker("トヨタ")
    assert result.ticker == "7203.T"
    assert result.source == "dict"
    assert result.confidence >= 0.85


@pytest.mark.asyncio
async def test_resolve_apple_by_dict():
    from agents.ticker_resolver import resolve_ticker
    result = await resolve_ticker("アップル")
    assert result.ticker == "AAPL"
    assert result.source == "dict"


@pytest.mark.asyncio
async def test_resolve_unknown_returns_result():
    from agents.ticker_resolver import resolve_ticker
    result = await resolve_ticker("存在しない会社XYZ123")
    assert result.ticker is not None
    assert result.confidence <= 0.5


def test_resolve_result_model():
    from models.stock import ResolveResult
    r = ResolveResult(ticker="AAPL", confidence=0.9, source="regex")
    assert r.ticker == "AAPL"
    assert 0.0 <= r.confidence <= 1.0


def test_fetch_ticker_name_from_local_universe():
    """ローカルのユニバース (data/universe) からティッカー→企業名を引ける (ネット不要)。"""
    from agents.ticker_resolver import _local_name_for_ticker

    # jp.json に含まれる主力銘柄
    assert _local_name_for_ticker("7203.T") == "トヨタ自動車"
    assert _local_name_for_ticker("AAPL") == "Apple"
    # 未知ティッカーは None
    assert _local_name_for_ticker("NOSUCH.XX") is None
