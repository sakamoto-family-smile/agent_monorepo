"""HTML テーブル抽出 helper (リンク URL 込み)。

藤沢市の認可・認可外施設一覧 HTML には、施設名 / 住所 / 電話 / 公式 URL の表が含まれる。
`pandas.read_html` だけだとハイパーリンクの `href` が落ちるため、BeautifulSoup で行ごとに
(列インデックス → URL) のマップを取り出す (proposal 0003 §A4-3 の 2 段パイプライン)。

戻り値はテーブル単位の `HtmlTable` のリスト。各テーブルは:
    - `headers`: ヘッダ行 (`<th>`) のテキスト。なければ空 list
    - `rows`: 各行のセルテキスト (リンクの場合 anchor の text)
    - `row_links`: 各行ごとに `{列 index: URL}` の dict
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel, ConfigDict


class HtmlTable(BaseModel):
    """1 つの `<table>` を表すモデル。"""

    model_config = ConfigDict(frozen=True)

    headers: list[str]
    rows: list[list[str]]
    row_links: list[dict[int, str]]


def extract_tables_with_links(html: str) -> list[HtmlTable]:
    """HTML 内の全 `<table>` を `HtmlTable` のリストに変換する。

    - thead がある → thead の `<th>` を headers
    - thead が無いが 1 行目がすべて `<th>` → その行を headers
    - それ以外 → headers は空 list

    各セルテキストは strip 済。リンクは `<a href>` の値を `row_links[row_idx][col_idx]` に
    格納する (リンクが無い場合は dict のキーに含めない)。
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    tables: list[HtmlTable] = []
    for table in soup.find_all("table"):
        if not isinstance(table, Tag):
            continue
        headers, body_rows = _collect_rows(table)
        rows: list[list[str]] = []
        row_links: list[dict[int, str]] = []
        for tr in body_rows:
            cells: list[str] = []
            links: dict[int, str] = {}
            for col_idx, cell in enumerate(tr.find_all(["td", "th"])):
                cells.append(cell.get_text(strip=True))
                anchor = cell.find("a", href=True)
                if anchor is not None:
                    links[col_idx] = anchor["href"]
            rows.append(cells)
            row_links.append(links)
        tables.append(HtmlTable(headers=headers, rows=rows, row_links=row_links))
    return tables


def _collect_rows(table: Tag) -> tuple[list[str], list[Tag]]:
    """thead → headers、tbody → body rows を取り出す。"""
    thead = table.find("thead")
    headers: list[str] = []
    body_rows: list[Tag] = []

    if isinstance(thead, Tag):
        for tr in thead.find_all("tr"):
            for th in tr.find_all("th"):
                headers.append(th.get_text(strip=True))
        tbody = table.find("tbody")
        if isinstance(tbody, Tag):
            body_rows = [tr for tr in tbody.find_all("tr") if isinstance(tr, Tag)]
        else:
            body_rows = [tr for tr in table.find_all("tr") if isinstance(tr, Tag)]
        return headers, body_rows

    # thead 無し: 全 tr から headers と body を判別
    all_rows = [tr for tr in table.find_all("tr") if isinstance(tr, Tag)]
    if all_rows and _all_th(all_rows[0]):
        headers = [th.get_text(strip=True) for th in all_rows[0].find_all("th")]
        body_rows = all_rows[1:]
    else:
        body_rows = all_rows
    return headers, body_rows


def _all_th(tr: Tag) -> bool:
    cells = tr.find_all(["td", "th"])
    return bool(cells) and all(c.name == "th" for c in cells)


__all__ = ["HtmlTable", "extract_tables_with_links"]
