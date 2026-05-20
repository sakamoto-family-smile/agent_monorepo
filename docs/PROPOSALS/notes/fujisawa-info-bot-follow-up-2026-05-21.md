# fujisawa-info-bot follow-up backlog (2026-05-21)

| | |
|---|---|
| **作成** | 2026-05-21 |
| **対象** | fujisawa-info-bot Phase 2 完了後 (PR #142 / #143 / #144 merged) |
| **関連 proposal** | [`0004-fujisawa-info-bot.md`](../0004-fujisawa-info-bot.md) |

Phase 2 で意識的に deferred にした項目 + 設計上の "穴" を集約。 各 item は
README Phase Roadmap (Phase 3-8) に組み込むか、 独立 PR で対応する。

---

## A. `llm-client` Gemini 拡張 (proposal §4.5 整合)

| | |
|---|---|
| **優先度** | Medium |
| **トリガ** | Phase 7 (Cloud Run デプロイ) 完了後にコスト実測 |
| **影響範囲** | `llm-client` パッケージ (横断) — fujisawa-info-bot / lifeplanner-agent / tech-news-agent 全てに影響 |
| **判断基準** | Anthropic Vertex Claude の実コストが proposal §5.4 目標 (月 ¥3,000) を超えるか / Gemini への切替価値があるか |

### 背景
- proposal 0004 §4.5 は **Vertex Gemini 2.0 Flash** を sub-agent default、 **Gemini 2.5 Pro** を Supervisor とすることでコスト目標を月 ¥3,000 以下に設定
- Phase 2 (PR #144) は実装速度優先で `llm-client` 既存資産の **Vertex Anthropic Claude** を採用 → proposal §4.5 から逸脱
- `llm-client` には現在 Gemini クライアントが無い (`AnthropicLLMClient` / `VertexAnthropicLLMClient` / `MockLLMClient` のみ)

### 採るべきアクション
1. Phase 7 完了後、 Cloud Run + 実 KB で Anthropic Vertex Claude の実コストを 1 週間測定 (analytics-platform 連携想定)
2. proposal §5.4 のコスト試算と差分を出す
3. 差が大きい / Gemini 化の価値あり → `llm-client` 拡張 PR (`VertexGeminiLLMClient` 追加)
4. 差が小さい / Gemini 化の価値薄 → proposal 0004 §4.5 を Anthropic default に改訂し本件 close

### Out of scope
- LangGraph の `langchain-google-vertexai` 統合 (現状 Phase 2 では langgraph のみ使用)
- Gemini 専用の prompt 最適化

---

## B. proposal §5.4 コスト試算の Anthropic 単価での再評価

| | |
|---|---|
| **優先度** | Medium |
| **トリガ** | A と同タイミング (Phase 7 後) |
| **依存** | A (Gemini 化判断と同時に評価) |

proposal §5.4 は Gemini 単価前提 (Flash 1 メッセージ ¥0.05、 Pro ¥0.5)。
Anthropic Vertex Claude Haiku 4.5 の単価 / token 数で再計算し、 月 1 万メッセージ
想定での試算を更新する。

---

## C. LINE 3 秒タイムアウト + 同期実行の実測 → Phase 3 (Pub/Sub) 着手判断

| | |
|---|---|
| **優先度** | High (Phase 7 デプロイ前に確認したい) |
| **トリガ** | Phase 7 デプロイ後の初動確認 |

### 背景
- Phase 2 は同期実行 (webhook 内で LLM 呼出 → reply 完了)
- proposal §5.4 / DESIGN.md §4.0 で LINE 3 秒タイムアウト懸念を明記
- Cloud Run コールドスタート (1-3 秒) + Vertex Anthropic 初回呼出 (1-2 秒) で超過リスク

### アクション
1. Phase 7 デプロイ後、 cold start 含めた p95 reply latency を計測
2. 2.5 秒超なら Phase 3 (Pub/Sub 非同期化) を即着手
3. 安定的に 2 秒以下なら Phase 3 を後回しにし、 Phase 5 (KB ETL) / Phase 4 (Crawl) を優先

---

## D. proposal §4.5 LLM ルーティング表の更新

| | |
|---|---|
| **優先度** | Low |
| **トリガ** | A の判断が確定した後 |

A の結果に応じて以下のいずれか:
- Gemini 化決定 → §4.5 は現行のまま (理想形を維持)
- Anthropic 継続 → §4.5 を Anthropic 単価 + モデルに書き換え、 implementation history に経緯記録

---

## E. Vertex Anthropic Claude モデル名の妥当性確認

| | |
|---|---|
| **優先度** | Low |
| **トリガ** | Phase 7 デプロイ前 |

Phase 2 で default に置いた `claude-haiku-4-5@20251001` (`app/config.py`) は
**未検証**。 Vertex AI コンソールで region (us-east5) と model 名の組合せが
実在することを確認する。

---

## F. KB が空の状態での RAG no-hit 文言の改善

| | |
|---|---|
| **優先度** | Low |
| **トリガ** | Phase 5 (KB ETL) 完了後 |

Phase 5 でも KB が充実するまでは大半の質問が no-hit になる。 現状の固定文
("コンタクトセンターにお問い合わせください") は実用上適切だが、 KB が
"sitemap 数件しか入っていない" 過渡期は誤解を招く可能性あり。
Phase 5 デプロイ時の seeding 充足度に応じて文言を再評価する。

---

## G. Phase 5 (KB ETL) の実装方針確定

| | |
|---|---|
| **優先度** | High (次に着手) |
| **トリガ** | 本 backlog 確定後 |

### 検討事項
- `fujisawa-platform/etl/` の既存 Cloud Run Jobs (admission_results / facilities) と同じ枠組みで
  weekly_crawl batch を実装するか、 fujisawa-info-bot 内に持つか
- proposal 0004 §4.3 では `fujisawa-info-bot/app/batch/crawl_weekly.py` 想定だが、
  「fujisawa-platform 側で KB 投入 ETL を持つほうが共通基盤らしい」 という選択肢もある
- Phase 5 着手時に判断する (本 backlog に明記)

---

## 参照

- [`0004-fujisawa-info-bot.md`](../0004-fujisawa-info-bot.md) — proposal
- [`../../fujisawa-info-bot/docs/DESIGN.md`](../../../fujisawa-info-bot/docs/DESIGN.md) — Phase ごとの確定設計
- PR #144 — Phase 2 (本 backlog の発生源)
