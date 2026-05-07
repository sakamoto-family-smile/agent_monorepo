<!--
このファイルをコピーして `NNNN-your-title.md` にリネームし、
必須セクションを埋めてください。

凡例:
  [必須] 空にしない (書くことがなければ "N/A" と理由を記載)
  [推奨] 該当する場合のみ書く (不要なら節ごと削除可)
  HTML コメント (`<!-- ... -->`) は提出時に削除して OK

書き方の指針 / 採番ルール / ステータス遷移は `README.md` 参照。
-->

# PROPOSAL-NNNN: <短い日本語タイトル>

| | |
|---|---|
| **Status** | Draft <!-- Draft / In Review / Approved / Implementing / Implemented / Rejected / Deprecated --> |
| **Author** | @username |
| **Created** | YYYY-MM-DD |
| **Updated** | YYYY-MM-DD |
| **Target** | <agent name>  <!-- 例: lifeplanner-agent / piyolog-analytics / cross-agent --> |
| **Related PRs** | (none yet)  <!-- 実装着手後に #NNN を追記 --> |
| **Supersedes** | —  <!-- 旧提案を置き換える場合のみ --> |
| **Superseded by** | —  <!-- 後継提案ができたら記載 --> |

---

## [必須] 1. Summary

<!--
1-2 段落で「何を作るか / なぜ作るか」。
release notes やロードマップでそのまま引用される想定で書く。
-->

## [必須] 2. Motivation

<!--
背景・解決したい課題。「現状どう困っているか」「放置するとどうなるか」を書く。
-->

### [必須] 2.1 Goals

<!--
達成したいこと (測れる粒度で 3-5 個)。
- 例: 「LINE Bot から月次サマリを Flex で表示できる」
-->

- [ ] ...
- [ ] ...

### [必須] 2.2 Non-Goals

<!--
意図的にスコープ外とすること。あとから「これも欲しい」と言われた時の
判断材料になる。
- 例: 「リアルタイム push 通知は対象外 (Phase X 予定)」
-->

- ...
- ...

---

## [必須] 3. Proposal

<!--
何を作るかの本文。User Stories でユースケースを 1-2 個示すと伝わりやすい。
-->

### [推奨] 3.1 User Stories

<!--
家族メンバー視点のシナリオ。LINE Bot のような UX 重視機能では特に有用。
省略可だが、UX 機能なら書くのを推奨。
-->

#### 3.1.1 ストーリー 1
> ...

#### 3.1.2 ストーリー 2
> ...

### [推奨] 3.2 Notes / Constraints / Caveats

<!--
設計時の前提・既知の制約をここに集約する。
- 例: 「時間粒度は年単位、月単位プロレートは PR X で対応」
- 例: 「DEV_HOUSEHOLD_ID と LINE 連携の household_id がズレる罠」
-->

- ...

### [必須] 3.3 Risks and Mitigations

<!--
セキュリティ / データ消失 / PII / LLM 暴走 / コスト超過 など、想定リスクを列挙。
個人用途でも事故ると痛いので必須。
-->

| リスク | 影響度 | 対策 |
|---|---|---|
| 例: LINE webhook 署名検証漏れ | High | InvalidSignatureError で 401 返却、テストでカバー |
| 例: Vertex AI 連続呼び出しでコスト爆発 | Medium | 1 conversation = 最大 N tool iterations、PRRR/分単位の rate limit |

---

## [必須] 4. Design Details

<!--
具体的な技術仕様: API / DB / I/O / 関数シグネチャ / シーケンス図 等。
コードの抜粋・dataclass 定義・OpenAPI スニペット等を貼ると良い。
-->

### 4.1 アーキテクチャ概略

<!-- ASCII 図 or mermaid で OK -->

### 4.2 データモデル

<!-- DB スキーマ追加 / 変更がある場合 -->

### 4.3 API

<!-- 新規 / 変更されるエンドポイント -->

### 4.4 主要モジュール

<!-- どこに何を追加 / 変更するか -->

### [必須] 4.5 Test Plan

<!--
テスト方針。pytest の unit / integration を最低限カバー。
- 単体テスト: 純関数 / dataclass の境界
- 統合テスト: API 経由 / DB を実際に叩く / LINE webhook stub
- 手動確認: 実機での確認項目 (チェックリスト形式)
-->

- **Unit**: ...
- **Integration**: ...
- **Manual / E2E**: ...

### [推奨] 4.6 Migration / Rollback

<!--
DB スキーマ変更がある場合に必須。
- alembic migration の番号と内容
- 既存環境への影響 (= 既存ユーザーが何もしないと壊れるか)
- ロールバック手順 (downgrade / data の保全)
- env 追加 / 削除がある場合は本番反映時の手順
-->

- **Migration**: ...
- **Rollback**: ...
- **既存ユーザー影響**: ...

### [推奨] 4.7 Feature Enablement

<!--
env / config で機能を ON/OFF できるか。
- どの env / config で切り替えるか
- 無効化時の挙動 (silent skip / 503 エラー / etc.)
-->

- ...

---

## [推奨] 5. Operational Concerns

<!--
運用に関する観点。本番デプロイ後にトラブったときの参考に。
-->

### 5.1 Monitoring

<!--
動作確認方法を簡潔に書く。SLI/SLO の数値目標までは不要。
- どの Cloud Logging クエリ / metric / analytics-platform イベントを見るか
- 「正常時はこうなる」「異常時はこうなる」のサンプル
-->

- ...

### 5.2 Troubleshooting

<!--
予想される詰まりどころ + 対処。
| 症状 | 原因 / 対処 |
-->

| 症状 | 原因 / 対処 |
|---|---|
| ... | ... |

### 5.3 Dependencies

<!--
依存する外部サービス / 他エージェント / ライブラリ
- LINE Messaging API
- Vertex AI / Anthropic API
- analytics-platform
- Cloud SQL / Secret Manager / IAM
-->

- ...

### [推奨] 5.4 Non-Functional Requirements

<!--
この機能特有の NFR を書く。システム全体の NFR (月額予算 / 全体可用性 等)
は per-system design template (docs/SYSTEM_DESIGN_TEMPLATE.md, 将来作成)
の方に書く。該当しない項目は削除して構わない。

凡例:
- 性能: 応答時間 / throughput / 計算量
- コスト: LLM 呼出回数 / cloud 課金 / ストレージ
- プライバシー: PII 扱い / データ保持期間
- キャパシティ: 同時接続 / DB レコード / JSON サイズ
- セキュリティ: auth / authz / secret / rate limit (Risks と重複時はそちらに集約)
-->

#### 性能 (Performance)
- 応答時間目標: <!-- 例: LINE webhook 3 秒以内、画像生成 5 秒以内 -->
- スループット: <!-- 例: 1 家族あたり 1 日 N 回想定 -->
- 計算量: <!-- 例: O(years × categories) = 600 ループ程度 -->

#### コスト (Cost)
- LLM 呼出: <!-- 例: 1 conversation あたり Vertex AI ¥X 以下 (モデル × tokens) -->
- ストレージ / 計算: <!-- 例: Cloud SQL 追加 X GB、Cloud Run minInstances 据え置き -->

#### プライバシー / データ保持
- PII 扱い: <!-- 例: raw text は DB のみ、analytics は sha256 hash で emit -->
- 保持期間: <!-- 例: conversation 履歴 90 日、ログ 30 日 -->

#### キャパシティ
- <!-- 例: 同時 10 ユーザーまで / DB レコード 10 万件 / JSON カラム 5KB/scenario -->

---

## [推奨] 6. Drawbacks

<!--
この提案を採用しないほうが良い理由 (もしあれば)。
- 例: 実装コストが見合わないケース
- 例: 後で別の方針 (例: Web UI) で吸収するほうが綺麗
反論を先回りしておくと、レビューが早く進む。
-->

- ...

## [必須] 7. Alternatives

<!--
代替案と却下理由。1-3 案。
ADR としての意思決定根拠を残す重要パート。
-->

### 案 A: <別案の名前>
- 概要: ...
- 却下理由: ...

### 案 B: <別案の名前>
- 概要: ...
- 却下理由: ...

---

## [必須] 8. Implementation History

<!--
PR / 設計変更の履歴。merged 後に追記する。
最低でも「初稿」「Approved」「Implemented」の 3 マイルストーン。
-->

| 日付 | 種別 | 内容 |
|---|---|---|
| YYYY-MM-DD | Draft | 初稿 |
| YYYY-MM-DD | PR #NNN | ... |
| YYYY-MM-DD | Implemented | 全 PR merged、ステータス更新 |
