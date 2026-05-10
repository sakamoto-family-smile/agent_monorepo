"""extract_main_text のテスト。

藤沢市 HP の HTML から `<main>` 本文 (またはそれに準ずるエリア) を抽出する。
nav / footer / script / style / aside は除去。
"""

from __future__ import annotations

from fujisawa_platform.etl._html import extract_main_text, extract_title


class TestExtractMainText:
    def test_returns_main_text(self) -> None:
        html = """
        <html><body>
            <header><nav>ナビ</nav></header>
            <main>
                <h1>ゴミ収集日</h1>
                <p>月曜 燃えるゴミ。</p>
                <p>水曜 資源ゴミ。</p>
            </main>
            <footer>フッタ</footer>
        </body></html>
        """
        text = extract_main_text(html)
        assert "ゴミ収集日" in text
        assert "月曜 燃えるゴミ" in text
        assert "ナビ" not in text
        assert "フッタ" not in text

    def test_strips_script_and_style(self) -> None:
        html = """
        <html><body>
            <main>
                <script>console.log('x');</script>
                <style>.x { color: red; }</style>
                <p>本文</p>
            </main>
        </body></html>
        """
        text = extract_main_text(html)
        assert "本文" in text
        assert "console.log" not in text
        assert "color: red" not in text

    def test_falls_back_to_article_when_no_main(self) -> None:
        html = """
        <html><body>
            <header>ヘッダ</header>
            <article>
                <h1>本文タイトル</h1>
                <p>本文段落</p>
            </article>
        </body></html>
        """
        text = extract_main_text(html)
        assert "本文タイトル" in text
        assert "本文段落" in text
        assert "ヘッダ" not in text

    def test_falls_back_to_body_when_no_main_no_article(self) -> None:
        html = """
        <html><body>
            <h1>シンプルな HTML</h1>
            <p>本文</p>
        </body></html>
        """
        text = extract_main_text(html)
        assert "シンプルな HTML" in text
        assert "本文" in text

    def test_collapses_consecutive_whitespace(self) -> None:
        html = """
        <html><body><main>
            <p>あいう    えお</p>
            <p>かきく</p>
        </main></body></html>
        """
        text = extract_main_text(html)
        # 連続空白は 1 つに、改行を保つ
        assert "    " not in text
        assert "あいう えお" in text

    def test_strips_aside_and_nav_inside_main(self) -> None:
        html = """
        <html><body>
            <main>
                <article>
                    <h1>記事</h1>
                    <p>本文段落</p>
                </article>
                <aside>関連リンク</aside>
                <nav>記事ナビ</nav>
            </main>
        </body></html>
        """
        text = extract_main_text(html)
        assert "本文段落" in text
        assert "関連リンク" not in text
        assert "記事ナビ" not in text

    def test_empty_html_returns_empty(self) -> None:
        assert extract_main_text("") == ""

    def test_returns_unicode_intact(self) -> None:
        html = "<html><body><main><p>令和6年4月入所選考</p></main></body></html>"
        text = extract_main_text(html)
        assert "令和6年4月入所選考" in text


class TestExtractTitle:
    def test_returns_title_tag_text(self) -> None:
        html = "<html><head><title>ゴミ収集日 | 藤沢市</title></head><body></body></html>"
        assert extract_title(html) == "ゴミ収集日 | 藤沢市"

    def test_falls_back_to_h1_when_no_title(self) -> None:
        html = "<html><body><h1>記事タイトル</h1></body></html>"
        assert extract_title(html) == "記事タイトル"

    def test_returns_none_when_neither_present(self) -> None:
        assert extract_title("<html><body></body></html>") is None

    def test_strips_whitespace(self) -> None:
        html = "<html><head><title>  タイトル  </title></head></html>"
        assert extract_title(html) == "タイトル"
