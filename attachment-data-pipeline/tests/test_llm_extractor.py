"""実 LLM 抽出器の経路を、ネットワーク不要のフェイククライアントで検証する。

実モデルが返しがちな出力 (```json フェンス・正しい値・単位欠落・捏造) を模した JSON を
返し、parse → grounding → 検証 → 採否 が期待通りかを確認する。実 API は不要。
"""

from __future__ import annotations

import json

from attachment_pipeline.contracts import Decision
from attachment_pipeline.eval.run_llm import financial_specs, score_extractions
from attachment_pipeline.extract.llm_extractor import LLMExtractor
from attachment_pipeline.synth.financial import generate_sample

# sample 70 の実値 (seed 固定):
#   net_sales_current = 437,000百万円 / net_sales_prior = 364,430百万円
#   securities_code = 7280 / company_name = 日本テクノロジー株式会社
_FAKE_REPLY = "```json\n" + json.dumps(
    {
        "fields": [
            # 正しい (単位込み) → 採用されるべき
            {"field_id": "net_sales_current", "value": "437,000百万円",
             "evidence": "当期売上高: 437,000百万円", "confidence": 0.95},
            {"field_id": "securities_code", "value": "7280",
             "evidence": "証券コード: 7280", "confidence": 0.9},
            # 単位を落とした (=スケール誤り) → 接地失敗で reject されるべき
            {"field_id": "net_sales_prior", "value": "364,430",
             "evidence": "前期売上高: 364,430百万円", "confidence": 0.9},
            # 捏造 → reject されるべき
            {"field_id": "company_name", "value": "架空ホールディングス株式会社",
             "evidence": "会社名", "confidence": 0.8},
        ]
    },
    ensure_ascii=False,
) + "\n```"


class _FakeClient:
    def complete(self, *, system: str, user: str) -> str:
        return _FAKE_REPLY


def test_llm_path_parses_and_validates():
    sample = generate_sample(70)
    extractor = LLMExtractor(_FakeClient(), financial_specs())
    exts = extractor.extract(sample)
    # 4 件すべて parse される (空値・未知 field は無い)
    assert {e.field_id for e in exts} == {
        "net_sales_current", "securities_code", "net_sales_prior", "company_name",
    }

    decided = {d.field_id: d for d in score_extractions(sample, exts, tau=0.5)}
    # 正しい値は採用
    assert decided["net_sales_current"].decision is Decision.ACCEPT
    assert decided["net_sales_current"].value == "437000000000"
    assert decided["securities_code"].decision is Decision.ACCEPT
    # スケール誤り・捏造は棄却
    assert decided["net_sales_prior"].decision is Decision.REJECT
    assert decided["company_name"].decision is Decision.REJECT


def test_llm_lenient_json_parsing():
    """前後に散文が混じった出力でも JSON 本体を取り出せる。"""
    class _Noisy:
        def complete(self, *, system: str, user: str) -> str:
            return "了解しました。以下が抽出結果です。\n" + _FAKE_REPLY + "\n以上です。"

    sample = generate_sample(70)
    exts = LLMExtractor(_Noisy(), financial_specs()).extract(sample)
    assert any(e.field_id == "net_sales_current" for e in exts)
