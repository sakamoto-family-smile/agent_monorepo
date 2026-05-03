"""Phase 2: setup_richmenu の画像生成 + payload 構築検証。

LINE API 呼び出しは行わず、純関数のみテスト (HTTP は monkeypatch で stub)。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# scripts/ を import path に追加 (scripts/setup_richmenu.py)
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def test_render_richmenu_image_size() -> None:
    """生成画像が 2500x1686 で 8 セル全て描画されている (mode/size 確認)。"""
    from setup_richmenu import LARGE_HEIGHT, LARGE_WIDTH, NORMAL_CELLS, render_richmenu_image

    img = render_richmenu_image(NORMAL_CELLS)
    assert img.size == (LARGE_WIDTH, LARGE_HEIGHT)
    assert img.mode == "RGB"


def test_render_richmenu_image_wrong_cell_count() -> None:
    from setup_richmenu import CellSpec, render_richmenu_image

    with pytest.raises(ValueError):
        render_richmenu_image([CellSpec("a", "x", "action=help")])  # 1 cell のみ


def test_build_richmenu_payload_structure() -> None:
    """payload が LINE API 仕様 (size / areas / action.type=postback) に合致。"""
    from setup_richmenu import GRID_COLS, GRID_ROWS, NORMAL_CELLS, build_richmenu_payload

    payload = build_richmenu_payload(NORMAL_CELLS)
    assert payload["size"]["width"] == 2500
    assert payload["size"]["height"] == 1686
    assert payload["selected"] is True
    assert "areas" in payload
    assert len(payload["areas"]) == GRID_COLS * GRID_ROWS

    # 全 area が postback action で、bounds がグリッド通り
    for idx, area in enumerate(payload["areas"]):
        assert area["action"]["type"] == "postback"
        assert "data" in area["action"]
        assert "displayText" in area["action"]
        col = idx % GRID_COLS
        row = idx // GRID_COLS
        assert area["bounds"]["x"] == col * (2500 // GRID_COLS)
        assert area["bounds"]["y"] == row * (1686 // GRID_ROWS)


def test_payload_postback_data_matches_postback_router_actions() -> None:
    """各セルの postback_data が postback_router.handle_postback で
    エラーにならないことを軽く検証 (同じ syntax を持つ)。"""
    from setup_richmenu import NORMAL_CELLS

    actions = {c.postback_data.split("&")[0].split("=")[1] for c in NORMAL_CELLS}
    assert actions <= {"summary", "chart", "consult", "help"}


def test_main_dry_run_creates_image(tmp_path) -> None:
    """--dry-run で LINE API 呼ばずに PNG が生成されることを確認。"""
    from setup_richmenu import main

    out = tmp_path / "rm"
    rc = main(["--dry-run", "--output-dir", str(out)])
    assert rc == 0
    image_files = list(out.glob("*.png"))
    assert len(image_files) == 1
    # PNG マジック
    assert image_files[0].read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_main_no_token_returns_error(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """非 dry-run + LINE_CHANNEL_ACCESS_TOKEN 未設定 → exit 2。"""
    from setup_richmenu import main

    monkeypatch.delenv("LINE_CHANNEL_ACCESS_TOKEN", raising=False)
    rc = main(["--output-dir", str(tmp_path)])
    assert rc == 2


def test_create_richmenu_calls_correct_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_richmenu が LINE API の正しい URL に POST する。"""
    from setup_richmenu import LINE_API_BASE, create_richmenu

    captured: dict = {}

    class _FakeResp:
        status_code = 200
        text = "{}"

        def json(self):
            return {"richMenuId": "richmenu-test-123"}

    def _fake_post(url, headers=None, content=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["content"] = content
        return _FakeResp()

    monkeypatch.setattr("httpx.post", _fake_post)
    rid = create_richmenu(
        access_token="t", payload={"size": {"width": 2500, "height": 1686}}
    )
    assert rid == "richmenu-test-123"
    assert captured["url"] == f"{LINE_API_BASE}/richmenu"
    assert captured["headers"]["Authorization"] == "Bearer t"


def test_upload_image_uses_content_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """upload_richmenu_image は api-data.line.me に PUT する。"""
    from setup_richmenu import LINE_CONTENT_API_BASE, upload_richmenu_image

    captured: dict = {}

    class _FakeResp:
        status_code = 200
        text = ""

    def _fake_post(url, headers=None, content=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return _FakeResp()

    monkeypatch.setattr("httpx.post", _fake_post)
    upload_richmenu_image(
        access_token="t", rich_menu_id="rid", image_bytes=b"fake-png"
    )
    assert captured["url"] == f"{LINE_CONTENT_API_BASE}/richmenu/rid/content"
    assert captured["headers"]["Content-Type"] == "image/png"


def test_set_default_richmenu_calls_correct_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    from setup_richmenu import LINE_API_BASE, set_default_richmenu

    captured: dict = {}

    class _FakeResp:
        status_code = 200
        text = ""

    def _fake_post(url, headers=None, timeout=None):
        captured["url"] = url
        return _FakeResp()

    monkeypatch.setattr("httpx.post", _fake_post)
    set_default_richmenu(access_token="t", rich_menu_id="rid")
    assert captured["url"] == f"{LINE_API_BASE}/user/all/richmenu/rid"
