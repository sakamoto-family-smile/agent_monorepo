"""LINE 返信テキストの整形（純粋関数）。

副作用がないので単体テストしやすい。route はここを呼ぶだけにする。
"""

from __future__ import annotations

from urllib.parse import urlencode

from app.models import EntryDraft, RosterEntry

# 一覧・検索結果で返す最大件数（LINE の可読性のため）。
MAX_RESULTS = 20


def format_entry_line(entry: RosterEntry) -> str:
    """1 レコードを 1 ブロックのテキストに整形する。"""
    parts = [f"◾ {entry.name}（{entry.relation.value}）"]
    if entry.zip or entry.address:
        zip_prefix = f"〒{entry.zip} " if entry.zip else ""
        parts.append(f"　{zip_prefix}{entry.address}")
    if entry.note:
        parts.append(f"　メモ: {entry.note}")
    return "\n".join(parts)


def format_search_results(entries: list[RosterEntry], query: str) -> str:
    """検索結果一覧を返信テキストにする。"""
    if not entries:
        return f"「{query}」に一致する名簿はありませんでした。"
    shown = entries[:MAX_RESULTS]
    header = f"「{query}」の検索結果: {len(entries)} 件"
    if len(entries) > MAX_RESULTS:
        header += f"（先頭 {MAX_RESULTS} 件を表示）"
    body = "\n\n".join(format_entry_line(e) for e in shown)
    return f"{header}\n\n{body}"


def help_text(register_url: str) -> str:
    """使い方の案内。"""
    lines = [
        "📇 名簿管理の使い方",
        "",
        "・登録: 下のフォームから入力",
        f"　{register_url}" if register_url else "　（リッチメニュー「登録」）",
        "・検索: 「検索 山田」のように送信",
        "・一覧: 「一覧」と送信",
        "・CSV 取り込み: CSV ファイルを送信 → 内容確認後「確定」",
        "・写真から登録: 名刺や封筒の写真を送信",
    ]
    return "\n".join(lines)


def build_register_url(base_url: str, prefill: EntryDraft | None = None) -> str:
    """LIFF 登録フォームの URL を作る。prefill があればクエリに載せる。"""
    if not base_url:
        return ""
    url = base_url.rstrip("/") + "/liff"
    if prefill is None:
        return url
    params = {
        k: v
        for k, v in {
            "name": prefill.name,
            "kana": prefill.kana,
            "zip": prefill.zip,
            "address": prefill.address,
            "relation": prefill.relation,
            "note": prefill.note,
        }.items()
        if v
    }
    if not params:
        return url
    return f"{url}?{urlencode(params)}"


__all__ = [
    "MAX_RESULTS",
    "build_register_url",
    "format_entry_line",
    "format_search_results",
    "help_text",
]
