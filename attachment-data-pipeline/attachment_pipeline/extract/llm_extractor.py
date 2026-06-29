"""実 LLM 抽出器 (sync)。

設計ガイドの要点を遵守:
  - オフセットは LLM に出させない (値と evidence_span のみ。位置は検証側がコードで逆引き)
  - 値は原文文字列のまま返させる
  - 長文はチャンク分割して各チャンクを抽出 → field_id でマージ

``client`` は ``complete(system: str, user: str) -> str`` を満たせばよい (duck typing)。
- 実モデル: ``build_anthropic_client()`` が anthropic SDK 経由の同期クライアントを返す。
- テスト: 決め打ち JSON を返すフェイクで end-to-end を検証 (ネットワーク不要)。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from ..contracts import ExtractionResult
from ..schema import FieldType
from ..synth.generator import GoldSample
from ..validate.chunking import chunk_text

_CHUNK_THRESHOLD = 6000  # これを超える原文はチャンク分割して抽出


class SyncLLMClient(Protocol):
    def complete(self, *, system: str, user: str) -> str: ...


@dataclass(frozen=True)
class FieldSpec:
    """抽出対象フィールドの仕様 (プロンプト生成に使う)。"""

    field_id: str
    field_type: FieldType
    description: str  # 人間可読の説明 (例: 当期の売上高)


_SYSTEM = (
    "あなたは文書から指定フィールドを抽出するエンジンです。"
    "各フィールドについて、値を『原文に現れる文字列のまま』返してください"
    "(単位・記号・桁区切りも原文どおり。言い換え・要約・正規化・文字位置は出力しない)。"
    "値とともに、その値を含む原文の短い一節(evidence)と確信度(0〜1)を返してください。"
    "原文に該当が見つからない、または確信が持てないフィールドは value を空文字にしてください。"
    "出力は次の JSON のみ: "
    '{"fields":[{"field_id":str,"value":str,"evidence":str,"confidence":number}]}'
)


def _build_user_prompt(text: str, specs: list[FieldSpec]) -> str:
    lines = "\n".join(f"- {s.field_id}: {s.description}" for s in specs)
    return f"# 抽出対象フィールド\n{lines}\n\n# 原文\n{text}\n"


class LLMExtractor:
    """実 LLM で抽出する。長文はチャンク分割して field_id でマージ。"""

    def __init__(self, client: SyncLLMClient, specs: list[FieldSpec]) -> None:
        self._client = client
        self._specs = specs
        self._spec_by_id = {s.field_id: s for s in specs}

    def extract(self, sample: GoldSample) -> list[ExtractionResult]:
        text = sample.text
        if len(text) <= _CHUNK_THRESHOLD:
            return self._extract_span(text, 0)
        merged: dict[str, ExtractionResult] = {}
        for chunk in chunk_text(text):
            for r in self._extract_span(chunk.text, chunk.global_start):
                prev = merged.get(r.field_id)
                # 同一 field は確信度が高い方を採用 (チャンク境界の重複対策)。
                if prev is None or r.extract_conf > prev.extract_conf:
                    merged[r.field_id] = r
        return list(merged.values())

    def _extract_span(self, text: str, global_start: int) -> list[ExtractionResult]:
        raw = self._client.complete(system=_SYSTEM, user=_build_user_prompt(text, self._specs))
        return self._parse(raw, global_start)

    def _parse(self, raw: str, global_start: int) -> list[ExtractionResult]:
        data = _loads_lenient(raw)
        results: list[ExtractionResult] = []
        for item in data.get("fields", []):
            field_id = item.get("field_id")
            value = (item.get("value") or "").strip()
            spec = self._spec_by_id.get(field_id)
            if spec is None or not value:
                continue  # 未知フィールド・空値は抽出側で出さない
            results.append(
                ExtractionResult(
                    field_id=field_id,
                    field_type=spec.field_type,
                    value=value,
                    evidence_span=item.get("evidence") or value,
                    chunk_id=0,
                    global_start=global_start,
                    extract_conf=float(item.get("confidence", 0.5)),
                )
            )
        return results


def _loads_lenient(raw: str) -> dict:
    """```json フェンスや前後の散文を許容して JSON 本体を取り出す。"""
    s = raw.strip()
    if "```" in s:
        # 最初のコードフェンス内を優先的に拾う
        parts = s.split("```")
        for p in parts:
            p = p.removeprefix("json").strip()
            if p.startswith("{"):
                s = p
                break
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"LLM 出力から JSON を抽出できません: {raw[:120]!r}")
    return json.loads(s[start : end + 1])


def build_anthropic_client(model: str = "claude-haiku-4-5-20251001") -> SyncLLMClient:
    """anthropic SDK 経由の同期クライアントを返す。

    認証は環境変数 (ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL) に従う。anthropic 未導入や
    キー未設定なら明示的に失敗する (静かに動かない事態を避ける)。
    """
    try:
        import anthropic
    except ModuleNotFoundError as e:  # pragma: no cover - 実行環境依存
        raise RuntimeError("anthropic 未導入。`uv pip install anthropic` を実行してください。") from e

    sdk = anthropic.Anthropic()  # ANTHROPIC_API_KEY/BASE_URL を読む

    class _Client:
        def complete(self, *, system: str, user: str) -> str:
            resp = sdk.messages.create(
                model=model,
                max_tokens=2048,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")

    return _Client()
