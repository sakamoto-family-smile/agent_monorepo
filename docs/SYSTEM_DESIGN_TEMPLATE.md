<!--
このファイルをコピーして `<agent>/docs/DESIGN.md` などにリネームし、
[必須] セクションを埋めてください。

凡例:
  [必須] 空にしない (書くことがなければ "N/A" と理由を記載)
  [推奨] 該当する場合のみ書く (不要なら節ごと削除可)
  [不要] 削除して構わない (現状の規模では過剰、参考までに残置)

このテンプレは「1 エージェント全体の設計書」を書くもの。1 つの機能追加に
ついての提案 / ADR は `docs/PROPOSALS/TEMPLATE.md` を使うこと。

書き方の指針 / 採番ルール / 移行方針は `docs/README.md` 参照。
-->

# <Agent / Platform name> 設計書

| | |
|---|---|
| **Version** | 0.1 |
| **最終更新** | YYYY-MM-DD |
| **Status** | Draft <!-- Draft / Active / Deprecated --> |
| **Owner** | @username |
| **README** | [`README.md`](../README.md) |

## 変更履歴

<!--
最低でも初版作成 + 大きな改訂を残す。細かい修正は git log で十分。
-->

| 日付 | Version | 変更内容 |
|---|---|---|
| YYYY-MM-DD | 0.1 | 初版 |

---

## [必須] 0. Executive Summary

<!--
1-2 段落で「何をするエージェントか / 想定ユーザー / 主要機能」を要約。
README の冒頭文より少し詳しいレベル。
-->

---

## [必須] 1. 目的・スコープ

### 1.1 目的

<!--
このシステムが解決する課題。なぜ作るか。
-->

### 1.2 想定ユーザー

<!--
誰が使うか。家族 / 開発者 / 自動化スクリプト 等。
個人プロジェクトでも明示しておくと「あれ、これ何のため？」が防げる。
-->

### 1.3 スコープ / Non-Goals

<!--
- やること
- 意図的にやらないこと (誤解防止)
-->

---

## [必須] 2. 機能要件

<!--
F1 / F2 / ... の形式で機能を列挙。
- 優先度: High / Mid / Low
- Phase: どの実装フェーズで入るか (Phase 1 / Phase 4 等)
- 状態: ✅ 実装済 / ⏳ 計画中 / ❌ 未着手

「機能個別の詳細設計」は per-feature proposal (docs/PROPOSALS/) に切り出す。
ここはタイトル + 1 行説明 + リンクで OK。
-->

| ID | 機能 | 状態 | Phase | Proposal |
|---|---|---|---|---|
| F1 | ... | ✅ 実装済 | Phase 1 | — |
| F2 | ... | ⏳ 計画中 | Phase 4 | [#NNNN](PROPOSALS/NNNN-xxx.md) |

---

## [必須] 3. 非機能要件 (NFR)

<!--
システム全体の NFR。機能個別の NFR は各 proposal の `5.4` で書く。
規模が小さい (家族数人) ので、ガチガチの SLA 数値は不要。
「目標値・許容範囲・既知の制約」を 1 行ずつでよい。
-->

### 3.1 性能

<!-- 例: LINE webhook 3 秒以内 / API レスポンス p95 < 500ms / 起動 30 秒以内 -->

### 3.2 可用性

<!-- 例: Cloud Run リージョン JP、家族用なので 99% で十分 / 計画停止 OK -->

### 3.3 セキュリティ

<!--
- 認証・認可方式
- secret 管理 (Secret Manager / .env / Workload Identity)
- PII の扱い (DB encryption / log scrubbing)
- security-platform 連携の有無
-->

### 3.4 コスト

<!--
- 月額予算の目安 (例: Cloud Run + SQL + Vertex AI で ¥3,000/月)
- LLM 呼出回数の上限 / レート
- ストレージ / データ転送
-->

### 3.5 プライバシー / データ保持

<!--
- 保存するデータの種類 (PII か否か)
- 保持期間 (例: トランザクション 永続 / ログ 30 日)
- バックアップ先 (例: GCS bucket、retention)
-->

### 3.6 キャパシティ

<!--
- 想定ユーザー数 / 同時接続
- DB サイズの上限想定
- スケーラビリティの設計判断 (例: 1 家族 1 Cloud Run instance)
-->

### 3.7 保守性 / テスト性

<!--
- カバレッジ目標 (例: 80%)
- lint (ruff) / type check (mypy) の方針
- observability (analytics-platform 連携、OTel)
-->

---

## [必須] 4. データモデル

<!--
主要テーブル / スキーマ / 関係。
ER 図 / mermaid 図 でも良い。詳細な DDL は alembic migration を参照。

例:
  households (家族)
    └── transactions (取引)
    └── scenarios (シナリオ)
        └── life_events (ライフイベント)
        └── simulation_results (結果)
-->

```
<ER 図 or 表>
```

### 4.1 主要テーブル

<!-- 表形式で 1 行 1 テーブル。詳細は alembic 参照 -->

| テーブル | 用途 | 主キー | 関連 |
|---|---|---|---|
| ... | ... | ... | ... |

---

## [必須] 5. アーキテクチャ

<!--
コンポーネント図 + データフロー。詳細は per-feature proposal で個別記述。
-->

### 5.1 コンポーネント

```
<ASCII / mermaid 図>
```

### 5.2 主要モジュール

<!--
- app/agents/ — XX
- app/services/ — YY
- app/repositories/ — ZZ
-->

### 5.3 外部連携

| 連携先 | 用途 | 認証方式 |
|---|---|---|
| LINE Messaging API | webhook / push | Channel Access Token |
| Vertex AI | LLM | ADC |
| analytics-platform | 業務ログ集約 | path dep |
| ... | ... | ... |

---

## [推奨] 6. 開発フェーズ / Roadmap

<!--
ハイレベルな Phase 一覧 + 状態。複数 PR にまたがる中粒度ロードマップは
別 doc (例: lifeplanner-agent/docs/LINE_ROADMAP.md) に切り出して link する。
ここでは Phase 1/2/3 などの大局的なマイルストーンに留める。
-->

| Phase | 名前 | スコープ | 状態 |
|---|---|---|---|
| Phase 0 | 基盤 | ... | ✅ 完了 |
| Phase 1 | MVP | ... | ✅ 完了 |
| Phase 2 | ... | ... | ⏳ 進行中 |
| Phase 3+ | ... | ... | 📋 計画 |

詳細 Roadmap: <!-- 例: [LINE_ROADMAP.md](LINE_ROADMAP.md) (該当する場合のみ) -->

---

## [必須] 7. 設計判断ログ (ADR-lite)

<!--
大きな設計判断のメモ。1 行 = 1 判断。詳細な根拠 (代替案・トレードオフ) が
必要なものは docs/PROPOSALS/NNNN-... に切り出して link する。

例:
| 2026-04-23 | SQLite を採用 (Postgres は Phase 4+) | 個人運用 + 単一プロセス前提、運用コスト 0 |
| 2026-05-01 | LLM_PROVIDER=vertex を default | Anthropic API 直呼出より GCP IAM で統制が効く |
-->

| 日付 | 判断 | 理由 | 詳細 |
|---|---|---|---|
| YYYY-MM-DD | ... | ... | — / [#NNNN](PROPOSALS/NNNN-xxx.md) |

---

## [推奨] 8. 運用

<!--
詳細は別 doc (DEPLOY.md / BACKUP_RESTORE.md / SETTINGS.md) があれば link、
無ければここに簡潔に書く。

OPERATIONS_TEMPLATE.md (将来作成) との棲み分け:
  - ここ: 概要・全体像 (どの doc にどの手順があるか)
  - OPERATIONS_TEMPLATE.md: 個別手順の詳細 (deploy / backup / restore)
-->

### 8.1 デプロイ

<!-- 例: docs/DEPLOY.md 参照 / Makefile target / 1 行 deploy コマンド例 -->

### 8.2 バックアップ / リストア

<!-- 例: docs/BACKUP_RESTORE.md 参照 -->

### 8.3 モニタリング

<!-- どこを見れば動作確認できるか (Cloud Logging クエリ / Phoenix UI 等) -->

---

## [必須] 9. セキュリティ・プライバシー

<!--
NFR 3.3 / 3.5 をより詳細に。データ分類 + 既知の脆弱性 + 残課題。
-->

### 9.1 データ分類

| 種類 | 例 | 取扱い |
|---|---|---|
| PII | LINE userId / 取引明細 | DB のみ、log には sha256 hash |
| 機密 | LINE channel secret / DB password | Secret Manager のみ |
| 公開可 | shared scenario id / public docs | — |

### 9.2 認証・認可

<!-- LINE webhook 署名検証 / LIFF ID トークン / DEV_HOUSEHOLD_ID fallback 等 -->

### 9.3 既知のリスク・残課題

<!-- security-platform スキャンで up-to-date のはずだが、設計時点で認識する課題 -->

---

## [必須] 10. テスト戦略

<!--
- unit / integration / E2E の役割分担
- カバレッジ目標 (例: 全体 80%, agents/ は 90%)
- CI で何を回すか (pytest / ruff / mypy / 統合テスト)
- 手動 QA が必要な箇所
-->

| レイヤ | 対象 | カバレッジ目標 |
|---|---|---|
| Unit | 純関数 / dataclass / utility | 90% |
| Integration | route / repository / service 間連携 | 80% |
| E2E | LINE webhook → DB → reply の通し | 主要シナリオのみ |

---

## [必須] 11. 関連ドキュメント

- [`README.md`](../README.md) — Quickstart / 環境変数 / API 一覧
- [`PROPOSALS/`](PROPOSALS/) — 機能個別の設計判断 (ADR 兼用)
- <!-- DEPLOY.md / BACKUP_RESTORE.md / SETTINGS.md 等該当するもの -->

---

## [推奨] 12. 用語集

<!--
独自用語 / 略語があれば。家族メンバーやレビュアーが迷わないように。
-->

| 用語 | 意味 |
|---|---|
| household_id | 1 家族を束ねる ID。複数 LINE userId を集約する単位 |
| ... | ... |
