"""`/api/line/image/{id}.png` / `/api/line/report/{id}.md` 配信 route の unit テスト。

route ハンドラを直接呼び、status / ヘッダ / body を検証する (ASGI 起動不要)。
"""

from __future__ import annotations

import pytest

from routes.media import get_image, get_report
from services.blob_store import get_image_store, get_report_store, reset_blob_stores

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset():
    reset_blob_stores()
    yield
    reset_blob_stores()


async def test_get_image_returns_png():
    image_id = get_image_store().put(b"\x89PNG", "image/png")
    resp = await get_image(image_id)
    assert resp.status_code == 200
    assert resp.media_type == "image/png"
    assert resp.body == b"\x89PNG"


async def test_get_image_404_when_missing():
    resp = await get_image("unknown")
    assert resp.status_code == 404


async def test_get_report_returns_markdown_attachment():
    report_id = get_report_store().put(b"# Report\nhello", "text/markdown")
    resp = await get_report(report_id)
    assert resp.status_code == 200
    assert resp.media_type == "text/markdown"
    assert resp.body == b"# Report\nhello"
    cd = resp.headers["content-disposition"]
    assert cd.startswith("attachment;")
    assert cd.endswith('.md"')


async def test_get_report_404_when_missing():
    resp = await get_report("unknown")
    assert resp.status_code == 404


async def test_get_report_html_inline():
    from routes.media import get_report_html

    rid = get_report_store().put(b"<html>r</html>", "text/html; charset=utf-8")
    resp = await get_report_html(rid)
    assert resp.status_code == 200
    assert resp.media_type == "text/html; charset=utf-8"
    # inline 表示なので Content-Disposition は付けない
    assert "content-disposition" not in {k.lower() for k in resp.headers.keys()}


async def test_get_report_html_404_when_missing():
    from routes.media import get_report_html

    resp = await get_report_html("unknown")
    assert resp.status_code == 404
