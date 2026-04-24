"""URL 正規化 + article_id のテスト。"""

from __future__ import annotations

from services.url_normalizer import article_id, normalize_url


def test_lowercase_scheme_and_host():
    assert (
        normalize_url("HTTPS://Cloud.Google.COM/blog/x/")
        == "https://cloud.google.com/blog/x"
    )


def test_strip_trailing_slash_except_root():
    assert normalize_url("https://example.com/a/") == "https://example.com/a"
    assert normalize_url("https://example.com/") == "https://example.com/"


def test_remove_fragment():
    assert (
        normalize_url("https://example.com/a#section-1")
        == "https://example.com/a"
    )


def test_remove_utm_params():
    assert (
        normalize_url(
            "https://example.com/a?utm_source=feed&utm_medium=rss&x=1"
        )
        == "https://example.com/a?x=1"
    )


def test_remove_various_tracking_params():
    assert (
        normalize_url(
            "https://example.com/a?fbclid=abc&gclid=def&mc_cid=1&_hsenc=x&y=keep"
        )
        == "https://example.com/a?y=keep"
    )


def test_sort_remaining_query_params_for_stable_hash():
    a = normalize_url("https://example.com/a?b=2&a=1")
    b = normalize_url("https://example.com/a?a=1&b=2")
    assert a == b


def test_article_id_is_stable_across_variants():
    variants = [
        "https://Cloud.Google.com/blog/x/?utm_source=feed",
        "https://cloud.google.com/blog/x",
        "https://cloud.google.com/blog/x/",
        "https://cloud.google.com/blog/x#section-2",
    ]
    ids = {article_id(v) for v in variants}
    assert len(ids) == 1


def test_article_id_differs_for_different_urls():
    assert article_id("https://a.com/x") != article_id("https://a.com/y")


def test_empty_and_invalid_urls_return_input_without_crashing():
    assert normalize_url("") == ""
    # スキーム無しは入力そのまま (trim のみ) を期待
    assert normalize_url("  not-a-url  ") == "not-a-url"


def test_article_id_length_is_32_hex():
    aid = article_id("https://example.com/a")
    assert len(aid) == 32
    assert all(c in "0123456789abcdef" for c in aid)
