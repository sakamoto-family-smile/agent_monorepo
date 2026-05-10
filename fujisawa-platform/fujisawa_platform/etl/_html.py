"""HTML 本文抽出 helper。

`weekly_crawl_etl` で藤沢市 HP の各 HTML ページから本文テキストを取り出すために使う。

抽出の優先順位:
    1. `<main>` (HTML5 の本文セマンティクス)
    2. `<article>` (記事本文がコンテンツ単位の場合)
    3. `<body>` (上記が無いシンプルな HTML)

除去対象:
    - `<script>` / `<style>` (実行コード)
    - `<nav>` / `<footer>` / `<header>` / `<aside>` (本文外の navi / 関連リンク)

Embedding に渡す前提なので、連続する空白は 1 つに正規化する。
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

_DROP_TAGS = ("script", "style", "nav", "footer", "header", "aside")
_WHITESPACE = re.compile(r"[ \t\u00a0\u3000]+")


def extract_main_text(html: str) -> str:
    """HTML から本文テキストを抽出する。

    Args:
        html: 取得した HTML 文字列。

    Returns:
        本文テキスト (連続空白は 1 つに正規化、改行は保つ)。空 input は空文字。
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")

    # 不要タグを丸ごと削除 (内部テキストごと消す)
    for tag in _DROP_TAGS:
        for elem in soup.find_all(tag):
            elem.decompose()

    container = _pick_container(soup)
    if container is None:
        return ""

    raw = container.get_text(separator="\n", strip=True)
    return _normalize_whitespace(raw)


def extract_title(html: str) -> str | None:
    """HTML から記事タイトルを抽出する (優先順位: `<title>` → `<h1>`)。"""
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")

    title_tag = soup.find("title")
    if title_tag is not None and title_tag.string:
        text = title_tag.string.strip()
        if text:
            return text

    h1 = soup.find("h1")
    if h1 is not None:
        text = h1.get_text(strip=True)
        if text:
            return text

    return None


def _pick_container(soup: BeautifulSoup) -> Tag | None:
    """本文コンテナ候補を優先順位で選ぶ。"""
    for selector in ("main", "article"):
        elem = soup.find(selector)
        if isinstance(elem, Tag):
            return elem
    return soup.body if isinstance(soup.body, Tag) else None


def _normalize_whitespace(text: str) -> str:
    """連続する空白を 1 つに、改行はそのまま。"""
    lines = [_WHITESPACE.sub(" ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


__all__ = ["extract_main_text", "extract_title"]
