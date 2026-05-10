"""extract_tables_with_links のテスト。

藤沢市の認可・認可外施設一覧 HTML から、テーブル + 各行の (列インデックス → URL) を
取り出すための helper。pandas.read_html だとリンク URL が落ちるため、BeautifulSoup で
別途抽出する (proposal 0003 §A4-3 / 調査ノート §A4-3 の 2 段パイプライン)。
"""

from __future__ import annotations

from fujisawa_platform.etl._html_table import (
    HtmlTable,
    extract_tables_with_links,
)


class TestExtractTablesWithLinks:
    def test_extracts_simple_table(self) -> None:
        html = """
        <table>
            <thead><tr><th>施設名</th><th>所在地</th><th>電話</th></tr></thead>
            <tbody>
                <tr><td>藤沢保育園</td><td>朝日町 1-1</td><td>0466-12-3456</td></tr>
                <tr><td>辻堂保育園</td><td>辻堂 2-2</td><td>0466-22-3456</td></tr>
            </tbody>
        </table>
        """
        tables = extract_tables_with_links(html)
        assert len(tables) == 1
        t = tables[0]
        assert t.headers == ["施設名", "所在地", "電話"]
        assert t.rows == [
            ["藤沢保育園", "朝日町 1-1", "0466-12-3456"],
            ["辻堂保育園", "辻堂 2-2", "0466-22-3456"],
        ]
        # リンクなし
        assert t.row_links == [{}, {}]

    def test_extracts_links_per_row(self) -> None:
        html = """
        <table>
            <thead><tr><th>施設名</th><th>住所</th><th>HP</th></tr></thead>
            <tbody>
                <tr>
                    <td>藤沢保育園</td>
                    <td>朝日町 1-1</td>
                    <td><a href="https://example.com/fuji">外部</a></td>
                </tr>
                <tr>
                    <td><a href="https://example.com/tujido">辻堂保育園</a></td>
                    <td>辻堂 2-2</td>
                    <td></td>
                </tr>
            </tbody>
        </table>
        """
        tables = extract_tables_with_links(html)
        assert len(tables) == 1
        t = tables[0]
        assert t.row_links == [
            {2: "https://example.com/fuji"},
            {0: "https://example.com/tujido"},
        ]
        # テキストはリンクの場合 anchor の text を使う
        assert t.rows[1][0] == "辻堂保育園"

    def test_extracts_multiple_tables(self) -> None:
        html = """
        <h2>公立保育所</h2>
        <table>
            <tr><th>施設名</th></tr>
            <tr><td>A</td></tr>
        </table>
        <h2>法人等保育所</h2>
        <table>
            <tr><th>施設名</th></tr>
            <tr><td>B</td></tr>
            <tr><td>C</td></tr>
        </table>
        """
        tables = extract_tables_with_links(html)
        assert len(tables) == 2
        assert tables[0].rows == [["A"]]
        assert tables[1].rows == [["B"], ["C"]]

    def test_handles_table_without_thead(self) -> None:
        """thead が無く 1 行目が th のテーブル。"""
        html = """
        <table>
            <tr><th>施設名</th><th>住所</th></tr>
            <tr><td>藤沢保育園</td><td>朝日町 1-1</td></tr>
        </table>
        """
        tables = extract_tables_with_links(html)
        assert tables[0].headers == ["施設名", "住所"]
        assert tables[0].rows == [["藤沢保育園", "朝日町 1-1"]]

    def test_handles_table_with_no_header_row(self) -> None:
        """全行 td のみのテーブル (ヘッダなし)。"""
        html = """
        <table>
            <tr><td>A</td><td>B</td></tr>
            <tr><td>C</td><td>D</td></tr>
        </table>
        """
        tables = extract_tables_with_links(html)
        assert tables[0].headers == []
        assert tables[0].rows == [["A", "B"], ["C", "D"]]

    def test_returns_empty_list_when_no_table(self) -> None:
        assert extract_tables_with_links("<html><body></body></html>") == []

    def test_strips_whitespace_in_cells(self) -> None:
        html = """
        <table>
            <tr><th>  施設名  </th></tr>
            <tr><td>  藤沢保育園  </td></tr>
        </table>
        """
        tables = extract_tables_with_links(html)
        assert tables[0].headers == ["施設名"]
        assert tables[0].rows == [["藤沢保育園"]]


class TestHtmlTableModel:
    def test_frozen(self) -> None:
        t = HtmlTable(headers=["a"], rows=[["1"]], row_links=[{}])
        try:
            t.headers = ["b"]  # type: ignore[misc]
            raise AssertionError("expected frozen model error")
        except Exception:
            pass
