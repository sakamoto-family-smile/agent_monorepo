# 精度検証ハーネス 設計 (Step 0: スコープ確定)

設計ガイド `high_precision_extraction.md` の **精度検証フェーズ** を、最短で定量化できる形に落とした実装スコープ。

## 0. 確定スコープ

| 項目 | 決定 | 理由 |
|---|---|---|
| 対象ドメイン | **請求書・領収書** | 数値中心でテーブル抽出の典型。`18800→800` の部分一致罠とスロット帰属ミス(C2)を両方検証できる |
| gold dataset | **合成-but-grounded** | 既知の構造化レコードから原文を生成 → 正解が自動で揃い、接地検証もしやすい。実データ待ちなしで着手可能 |
| v1 スコープ | **最小構成** | 接地 + 型別再検証 + スロット帰属 + Pydantic + τ棄却。NERクロスチェック/LLM検証(V5)/ReCoVERR/self-healing は v1 対象外 |
| LLM 依存 | **検証層は LLM 非依存・決定的** | 抽出器は Protocol で差し替え可能。精度検証は誤り注入Mock抽出器で決定的に回す(クレデンシャル不要) |

## 1. 確定スキーマ (請求書)

`attachment_pipeline/schema.py` の `Invoice` を正とする。各フィールドに **型別接地戦略** を割当てる(設計ガイド 4.5.4)。

| フィールド | 型 | 接地戦略 |
|---|---|---|
| `issuer_name` / `recipient_name` | name | fuzzy (rapidfuzz) |
| `issuer_address` | address | fuzzy |
| `invoice_no` | code | 完全一致 (厳密) |
| `issue_date` / `due_date` | date | 正規化後 完全一致 |
| `subtotal` / `tax` / `total` | amount | 語境界regex + 数値再検証(必須) |
| `line_items[].description` | name | fuzzy |
| `line_items[].quantity` | numeric | 語境界regex + 数値再検証 |
| `line_items[].unit_price` / `.amount` | amount | 語境界regex + 数値再検証 |

## 2. 評価指標 (precision優先)

正解は gold record。パイプライン出力 `DecidedField`(value or null)と突合する。

- **採用(accept)** = 値を出した、**棄却/abstain** = null。
- **正採用 (TP)**: 出力値が gold と正規化一致。
- **誤採用 (FP)**: 出力値が gold と不一致なのに採用。**precision の敵。設計目標は ≈0**。
- **正棄却 (TN)**: 抽出が誤りで、かつ null にできた(誤りを回避)。
- **過棄却 (FN)**: 抽出は正しかったのに null(recall 損)。

| 指標 | 定義 |
|---|---|
| **field precision** | TP / (TP + FP) — 採用値の正しさ。最重要 |
| **coverage** | (TP + FP) / 全フィールド — 埋めた割合 |
| **recall** | TP / 「正しく抽出できていたフィールド数」 |
| **hallucination ratio** | 接地できない値の比率(採用前に弾けた割合で評価) |
| **誤りモード別 捕捉率** | 注入した各誤り(部分一致罠/スロット入替/捏造/正規化ズレ)を検証層が reject できた割合 |

## 3. dev / test 分割

- 合成生成は seed 固定。`seed 0–69` を dev(τ・正規化ルール調整)、`seed 70–99` を test(最終報告)に固定分割。
- τ は dev split の risk–coverage で決め、test split は一度だけ測る。

## 4. v1 で測る主張

1. 検証層を通すと **誤採用(FP)が素の抽出より大幅に減る**(理想は 0)。
2. その代償としての coverage/recall 低下を定量化する(risk–coverage)。
3. **C2: スロット帰属ミス**(issuer↔recipient 入替)を evidence_span 帰属チェックで捕捉できることを示す。

## 5. v1 で意図的に対象外 (後続フェーズ)

- NER クロスチェック (V4 / GiNZA・dateparser)
- LLM 検証 (V5)
- ReCoVERR(証拠探索による復活)
- 校正(温度スケーリング) — labeled dev split が揃ってから導入
- self-healing CI / 監視

> レビュー指摘との対応: C1(2026年論文の要検証)は設計採否の問題で本ハーネスの外。C2(スロット帰属)は本 v1 で検証対象に含める。C3(正解必須)は合成goldで担保。H1(verbatim↔正規化衝突)は数値/日付型で「原文側・値側の双方を正規化して突合」する実装で対処。
