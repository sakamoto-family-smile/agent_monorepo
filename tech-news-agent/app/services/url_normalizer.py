"""URL 正規化 + 決定論的 article_id 生成。

URL 同一判定の困難さを正規化で吸収:
  - scheme / host は小文字化
  - 末尾スラッシュを除去 (ルートパス `/` は維持)
  - fragment (`#...`) を除去
  - UTM / その他トラッキング系クエリパラメータを除去
  - 残クエリパラメータをキー昇順でソート (順序揺れの吸収)
"""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# 正規化で削除するトラッキング系クエリパラメータ (先頭一致)
_TRACKING_PREFIXES: tuple[str, ...] = (
    "utm_",
    "mc_",       # MailChimp
    "_hsenc",    # HubSpot
    "_hsmi",
    "hsctatracking",
)

# 完全一致で削除するクエリパラメータ
_TRACKING_EXACT: frozenset[str] = frozenset(
    {
        "fbclid",
        "gclid",
        "ref",
        "ref_src",
        "source",
    }
)


def _is_tracking_param(key: str) -> bool:
    k = key.lower()
    if k in _TRACKING_EXACT:
        return True
    return any(k.startswith(p) for p in _TRACKING_PREFIXES)


def normalize_url(url: str) -> str:
    """URL を正規化。入力が不正なら元文字列をそのまま返す (ただし strip する)。"""
    raw = (url or "").strip()
    if not raw:
        return raw
    try:
        parts = urlparse(raw)
    except ValueError:
        return raw
    if not parts.scheme or not parts.netloc:
        return raw

    # クエリ: 順序ソート + トラッキング除去
    params = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not _is_tracking_param(k)
    ]
    params.sort()
    query = urlencode(params)

    # パス: 末尾スラッシュ除去 (ルートは維持)
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    return urlunparse(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            path,
            "",            # params (rarely used)
            query,
            "",            # fragment
        )
    )


def article_id(url: str) -> str:
    """正規化 URL から決定論的な article_id を生成。

    16 進数 32 文字 (128 bit) の短縮 ID。衝突耐性より idempotency を優先。
    用途: 「同じファイルを 2 回送っても重複登録されない」。
    """
    normalized = normalize_url(url)
    digest = hashlib.sha256(normalized.encode("utf-8"), usedforsecurity=False).hexdigest()
    return digest[:32]
