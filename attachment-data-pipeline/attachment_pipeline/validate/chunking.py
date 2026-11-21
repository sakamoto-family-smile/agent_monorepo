"""チャンク分割 (設計ガイド 4.5.2)。

長文を抽出の前段で分割する。各チャンクに ``global_start`` (原文内の開始位置) を保持し、
チャンク内ローカル位置に加算して原文全体のグローバルオフセットへ変換できるようにする。
分割は構造境界 (空行) を優先し、トークン上限を上限ガードとして併用、境界対策に
オーバーラップを付ける。
"""

from __future__ import annotations

from dataclasses import dataclass

_MAX_CHARS = 2000
_OVERLAP = 200


@dataclass(frozen=True)
class Chunk:
    """原文の一区間。global_start は原文内の開始オフセット。"""

    chunk_id: int
    text: str
    global_start: int

    def to_global(self, local: int) -> int:
        """チャンク内ローカル位置を原文グローバル位置へ変換。"""
        return self.global_start + local


def chunk_text(text: str, max_chars: int = _MAX_CHARS, overlap: int = _OVERLAP) -> list[Chunk]:
    """構造境界 (空行) でまとめつつ max_chars を上限に分割する。

    境界をまたぐ情報の取りこぼし対策として overlap 文字を次チャンク先頭に重ねる。
    overlap 由来の重複抽出は global offset をキーにマージ段で重複排除する想定。
    """
    if len(text) <= max_chars:
        return [Chunk(0, text, 0)]

    paragraphs = _split_keep_offsets(text)
    chunks: list[Chunk] = []
    cur_start = paragraphs[0][0] if paragraphs else 0
    cur_end = cur_start
    for start, end in paragraphs:
        # 現チャンクに段落を足すと上限超過 → 確定して次へ。
        if end - cur_start > max_chars and cur_end > cur_start:
            chunks.append(_make_chunk(text, len(chunks), cur_start, cur_end))
            cur_start = max(cur_end - overlap, 0)
        cur_end = end
    if cur_end > cur_start:
        chunks.append(_make_chunk(text, len(chunks), cur_start, cur_end))
    return chunks


def _make_chunk(text: str, chunk_id: int, start: int, end: int) -> Chunk:
    return Chunk(chunk_id=chunk_id, text=text[start:end], global_start=start)


def _split_keep_offsets(text: str) -> list[tuple[int, int]]:
    """空行 (\\n\\n) 区切りで (start, end) の段落範囲リストを返す (区切りは末尾に含める)。"""
    spans: list[tuple[int, int]] = []
    pos = 0
    n = len(text)
    while pos < n:
        nl = text.find("\n\n", pos)
        if nl == -1:
            spans.append((pos, n))
            break
        spans.append((pos, nl + 2))
        pos = nl + 2
    return spans
