"""実 LLM 抽出器スケルトン (llm-client 差し替え)。

検証層は LLM 非依存なので、本ファイルは精度検証の必須要素ではない。実運用で
``MockExtractor`` をこれに差し替えるための契約を示す。llm-client は optional 依存
(``pip install -e '.[llm]'``) のため遅延 import する。

設計ガイドの要点を遵守:
  - オフセットは LLM に出させない (値と evidence_span のみ。位置は検証側がコードで逆引き)
  - 値は原文文字列のまま返させる
  - 制約デコーディング (JSON) で構造を保証する
"""

from __future__ import annotations

import json
from typing import Any

from ..contracts import ExtractionResult
from ..schema import FIELD_TYPES, field_type_of
from ..synth.generator import GoldSample

_SYSTEM = (
    "あなたは請求書から指定フィールドを抽出するエンジンです。"
    "各フィールドについて、値を『原文に現れる文字列のまま』返してください。"
    "言い換え・要約・正規化・文字オフセットは絶対に出力しないこと。"
    "値とともに、その値を含む原文の前後一節 (evidence) と確信度 (0-1) を返してください。"
    "確信が持てないフィールドは value を空文字にしてください。"
)


def _build_user_prompt(text: str) -> str:
    fields = ", ".join(FIELD_TYPES.keys())
    return (
        f"# 原文\n{text}\n\n"
        f"# 抽出フィールド\n{fields} および line_items[].(description|quantity|unit_price|amount)\n\n"
        "# 出力 (JSON)\n"
        '{"fields": [{"field_id": str, "value": str, "evidence": str, "confidence": number}]}'
    )


class LLMExtractor:
    """``llm_client.protocol.LLMClient`` を受け取り抽出する。

    client は ``complete(system=..., user=...) -> str`` を満たせばよい。
    Gemini / Anthropic いずれも llm-client 経由で渡せる。
    """

    def __init__(self, client: Any, *, response_schema: dict | None = None) -> None:
        self._client = client
        self._schema = response_schema  # Gemini Controlled Generation 等に渡す想定

    async def extract(self, sample: GoldSample) -> list[ExtractionResult]:
        raw = await self._client.complete(system=_SYSTEM, user=_build_user_prompt(sample.text))
        return self._parse(raw, sample.text)

    def _parse(self, raw: str, text: str) -> list[ExtractionResult]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:  # 制約デコーディングが効かない経路の保険
            raise ValueError(f"LLM 出力が JSON として不正: {e}") from e

        results: list[ExtractionResult] = []
        for item in data.get("fields", []):
            value = (item.get("value") or "").strip()
            if not value:
                continue  # 空は抽出側で出さない
            field_id = item["field_id"]
            results.append(
                ExtractionResult(
                    field_id=field_id,
                    field_type=field_type_of(field_id),
                    value=value,
                    evidence_span=item.get("evidence", value),
                    chunk_id=0,
                    global_start=0,
                    extract_conf=float(item.get("confidence", 0.5)),
                )
            )
        return results
