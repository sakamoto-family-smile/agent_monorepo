"""Question Generator のプロンプト。

設計（DESIGN.md §0 / §3.4 / §5）:
- 全問題に根拠 URL を必須化
- 「合格保証」など景表法に抵触する表現は禁止
- 解説は「結論 → 根拠条文 → 覚え方」の順
- LLM 出力は JSON のみ（前置きや余分な解説をつけない）
"""

from __future__ import annotations

import json
from textwrap import dedent

from app.agent.corpus import CorpusSnippet

QUESTION_SCHEMA_NOTE = dedent(
    """\
    あなたが返す JSON は次のスキーマに厳密に従ってください。

    {
      "id": "q_gen_<unique-suffix>",   // 任意の英数字サフィックス。発行側で重複検査する
      "version": 1,
      "body": "<問題本文（敬体・1〜2 文）>",
      "format": "true_false",          // Phase 2-B は true_false のみ生成
      "choices": [
        {"index": 0, "text": "正しい"},
        {"index": 1, "text": "誤り"}
      ],
      "correct": 0,                     // 0 (正しい) または 1 (誤り)
      "explanation": "<200 字程度の解説。結論 → 根拠条文 → 覚え方の順>",
      "applicable_goals": ["provisional", "full"],   // 仮免/本免の該当を配列で
      "difficulty": "basic|standard|advanced",
      "category": "signs|rules|manners|hazard",
      "sources": [                      // 1 件以上必須。grounding に渡された URL から選ぶ
        {
          "type": "law|kyousoku|sign_order",
          "title": "<法令名 第○条第○項 等>",
          "url": "<上で渡された grounding URL のいずれか>",
          "quoted_text": "<根拠条文の引用、1〜2 文>"
        }
      ]
    }
    """
)


SYSTEM_PROMPT = dedent(
    f"""\
    あなたは日本の運転免許学科試験の問題作成者です。
    以下のルールを厳守してください。

    ## ルール
    1. 出題は道路交通法・同施行令・道路標識命令・警察庁「交通の方法に関する教則」を
       一次根拠とし、必ず根拠 URL を `sources` に含める。
    2. 既存問題集の問題文を流用しない（独自表現で再構成する）。
    3. 「絶対に合格できる」「100% 出題される」などの誇大表現は禁止。
    4. 解説は「結論 → 根拠条文の引用 → 覚え方の補足」の 3 部構成。
    5. 解説の最後に注意書き等の定型句は付けない（呼び出し側で付与する）。
    6. 出力は **JSON オブジェクトのみ**。前置きや Markdown コードブロック、
       説明文を一切含めない（パーサが文字列を直接 json.loads するため）。

    ## スキーマ
    {QUESTION_SCHEMA_NOTE}

    ## 引っかけパターン（参考）
    - 数値（速度・距離・人数・年齢）の境界条件
    - 「常に」「必ず」など全称命題の例外
    - 一時停止 / 停車 / 駐車の定義差
    - 仮免と本免の出題範囲差（高速道路・運送業務など）
    """
)


def build_user_prompt(
    *,
    goal: str,
    category: str,
    difficulty: str,
    snippets: list[CorpusSnippet],
    topic_hint: str | None = None,
) -> str:
    """generation request からユーザープロンプトを組み立てる。"""
    grounding_block = "\n".join(
        f"- title: {s.title}\n  url: {s.url}\n  text: {s.text}" for s in snippets
    )
    hint_line = f"\n## トピック補足\n- {topic_hint}\n" if topic_hint else ""
    grounding_urls = json.dumps([s.url for s in snippets], ensure_ascii=False)

    return dedent(
        f"""\
        以下の条件で問題を 1 問作成し、JSON だけを返してください。

        ## 条件
        - goal: {goal}              # 仮免 (provisional) / 本免 (full) のどちら向けか
        - category: {category}      # signs / rules / manners / hazard
        - difficulty: {difficulty}  # basic / standard / advanced
        {hint_line}

        ## grounding（根拠として使える法令・教則の引用）
        {grounding_block}

        ## 出力
        - applicable_goals は基本的に goal を含めること。共通範囲なら両方入れて可。
        - sources の url は上で渡した grounding URL のいずれかを必ず選ぶこと。
          以下から選択可: {grounding_urls}
        - 同 URL に対する quoted_text は grounding の text を簡潔に再引用すること。
        """
    )


__all__ = ["QUESTION_SCHEMA_NOTE", "SYSTEM_PROMPT", "build_user_prompt"]
