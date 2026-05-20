# category_routing Skill

藤沢市 LINE Bot に来る自然言語の質問を、 公式 HP の 7 カテゴリのどれを優先的に
検索すべきか分類するための prompt。 ユーザー発話 1 件に対して **カテゴリ 1 個** を
返す。 unsupervised に複数カテゴリを返させると後段の RAG が混線するため、
1 カテゴリに集約することを優先する。

## カテゴリ定義

| キー | 表示名 | 例 |
|---|---|---|
| `disaster` | 防災 | 「最寄りの避難所はどこ？」「台風きたらどこ逃げる？」 |
| `parenting` | 子育て | 「保育園の申込みどうやる？」「予防接種のスケジュール」 |
| `garbage` | ゴミ | 「鵠沼地区の燃えるゴミの日」「粗大ごみの出し方」 |
| `procedure` | 手続き | 「住民票どこで取れる？」「マイナンバーカード申請」 |
| `tourism` | 観光 | 「江ノ島の駐車場」「七夕まつり日程」 |
| `cityhall` | 市政情報 | 「市議会の議事録」「広報ふじさわ最新号」 |
| `other` | その他 | 上記いずれにも当てはまらない / 雑談 / 挨拶 |

## 出力フォーマット

```
{"category": "<key>", "confidence": <0.0-1.0>}
```

JSON 1 行のみ。 余計な前後の文字列は出力しない。

## 判断ルール

1. **キーワード優先**: 「ゴミ」「収集」「粗大」→ `garbage`、「保育園」「妊婦」「乳幼児」→ `parenting`、「避難」「警報」「地震」→ `disaster` のように明確な語彙があれば即決
2. **意図優先**: 「〜の出し方」「〜の申込み」のような行為動詞があれば、 対象が手続きカテゴリに該当するか判断
3. **疑わしいときは `other`**: 「藤沢ってどんな街？」のような曖昧な質問は `other` + 低 confidence

## 例

| ユーザー発話 | 出力 |
|---|---|
| 「ゴミの日いつですか？」 | `{"category": "garbage", "confidence": 0.95}` |
| 「最寄りの避難所」 | `{"category": "disaster", "confidence": 0.9}` |
| 「保育園の入りやすさ」 | `{"category": "parenting", "confidence": 0.85}` |
| 「江ノ島いきたい」 | `{"category": "tourism", "confidence": 0.8}` |
| 「こんにちは」 | `{"category": "other", "confidence": 0.6}` |

## Phase 2 時点での運用

Phase 2 では `category` を `KnowledgeStore.search_pages(category=...)` のフィルタに
そのまま渡す。 confidence < 0.5 の場合は category を None にしてフィルタ無しの
全体検索を行う (`rag.py` の判断)。
