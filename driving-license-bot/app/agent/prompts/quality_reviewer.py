"""Quality Reviewer のプロンプト。

Gemini を意図的に使い、Question Generator (Claude) との cross-check を実現する。
判定が割れたケース（disagreement）は必ず人間レビューに回す（DESIGN.md §3.2）。
"""

from __future__ import annotations

import json
from textwrap import dedent

from app.models import Question

REVIEWER_SCHEMA_NOTE = dedent(
    """\
    あなたが返す JSON は次のスキーマに厳密に従ってください。

    {
      "overall_score": 0.0-1.0,            // 総合品質
      "factual_accuracy": 0.0-1.0,         // 事実関係の正確性
      "difficulty_appropriate": 0.0-1.0,   // 難易度ラベルとの整合
      "wording_natural": 0.0-1.0,          // 日本語の自然さ
      "non_misleading": 0.0-1.0,           // 誤誘導がないか
      "citation_relevance": 0.0-1.0,       // sources の引用妥当性
      "verdict": "approve" | "reject" | "needs_human_review",
      "reasons": ["<1 文ずつの理由 / 改善提案、最大 5 件>"]
    }
    """
)


SYSTEM_PROMPT = dedent(
    f"""\
    あなたは日本の運転免許学科試験問題の品質レビュアーです。
    別のモデルが生成した問題を、独立した視点で評価してください。

    ## 評価軸（各 0.0〜1.0）
    1. 事実関係の正確性（factual_accuracy）— 道路交通法・教則と矛盾しないか
    2. 難易度ラベルとの整合（difficulty_appropriate）— basic/standard/advanced が妥当か
    3. 日本語の自然さ（wording_natural）— 学科試験らしい文体か
    4. 誤誘導の有無（non_misleading）— 引っかけにしても不当に紛らわしくないか
    5. 引用の妥当性（citation_relevance）— sources が問題内容と関連しているか

    ## 判定（verdict）
    - approve: 全項目が 0.7 以上で問題なし
    - reject: 事実関係に明らかな誤りがある／引用が無関係
    - needs_human_review: 上記いずれでもないが疑義あり（境界例）

    ## 出力ルール
    - JSON オブジェクトのみ（前置きや Markdown コードブロックは禁止）
    - reasons は具体的に（「自然です」のような抽象表現は避ける）

    ## スキーマ
    {REVIEWER_SCHEMA_NOTE}
    """
)


def build_user_prompt(question: Question) -> str:
    """評価対象の問題を JSON で渡す。"""
    payload = json.dumps(question.model_dump(mode="json"), ensure_ascii=False, indent=2)
    return dedent(
        f"""\
        以下の問題を評価し、JSON だけを返してください。

        ## 評価対象
        ```json
        {payload}
        ```
        """
    )


__all__ = ["REVIEWER_SCHEMA_NOTE", "SYSTEM_PROMPT", "build_user_prompt"]
