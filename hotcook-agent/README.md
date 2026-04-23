# ホットクック対応エージェント (hotcook-agent)

自動調理鍋ホットクック (シャープ KN-HW24H) を活用した、食材ベースの料理提案エージェント。
冷蔵庫にある食材から、ホットクックで作れるメニューをランキング形式で提案する。

> **本サービスは情報提供のみを目的としており、シャープ株式会社の公式サービスではありません。**
> メニュー番号 / 調理時間 / 予約調理可否 等は公開情報を参考にしていますが、実際の調理は本体液晶 / COCORO KITCHEN アプリの最新表示を優先してください。

---

## 概要

| 項目 | 内容 |
|---|---|
| 対象機種 | シャープ ヘルシオ ホットクック KN-HW24H (2.4L / 内蔵 145 メニュー) |
| Phase 1 シード | 30 メニュー (主要 7 カテゴリをカバー) |
| 技術スタック | Python 3.12 / FastAPI / Pydantic / SQLite / Claude Agent SDK (Phase 2 以降) |
| 動作環境 | ローカル MVP (Phase 1) → GCP (Phase 4 以降) |

---

## ロードマップ

### サマリ

| Phase | 内容 | ステータス |
|---|---|---|
| **A (Phase 1)** | ローカル MVP — 食材入力 → ホットクックメニュー提案 (ルールベース) | 🟡 **MVP 完了 / 残 TODO あり** |
| B (Phase 2) | Web UI + 在庫管理 (写真アップロード / Next.js) | ⬜ 未着手 |
| C (Phase 3) | 献立計画 + 学習 + LangGraph によるマルチエージェント化 + Reminders 連携 | ⬜ 未着手 |
| D (Phase 4) | GCP 移行 (Cloud Run + Firestore + Firebase Auth) | ⬜ 未着手 |
| E (Phase 5) | マルチユーザー対応 (家族別好み / FCM 通知) | ⬜ 未着手 |
| F (Phase 6) | 高度化 (栄養計算 / 買い物自動発注 / COCORO KITCHEN API 調査) | ⬜ 未着手 |

### Phase 1 残 TODO (PR #31 マージ後の継続作業)

PR #31 で MVP は動作するが、Phase 1 完了とするには以下が残っている。**Phase 2 着手の前 or 並行で消化**する想定。

- [ ] **menu-catalog 30 件の `verified: false → true` 化レビュー** — 取扱説明書 / シャープ公式メニューサイトと照合し、`menu_no` / `cook_minutes` / `mixer_required` / `reservation_ok` を確認
- [ ] **agent モード実装** — `mode="agent"` 指定時に Claude Agent SDK + `data/skills/hotcook-recipes/SKILL.md` を読み込んで根拠テキストをリッチ化 (現状はルールベースの根拠のみ)
- [ ] **CLI フロントエンド** — 仕様書に "CLI / Web UI" とあった部分。`scripts/cli.py` で対話式に食材入力 → 提案表示 (Phase 2 で Web UI を作る前の検証用)
- [ ] **PDF パイプラインのプロトタイプ** — `scripts/extract_menu_pdf.py`。シャープ公式 PDF (取扱説明書) → menu-catalog.json の差分追加。Phase 2 でカタログを 145 件まで広げる準備
- [ ] **Phoenix トレース表示の動作確認** — 既に `OTEL_EXPORTER_OTLP_ENDPOINT` で送信される設定だが、実 Phoenix インスタンスで span が見えるかは未検証

### Phase 2 — Web UI + 在庫管理 (目安 2 週間)

- [ ] Next.js 15 (App Router) で MVP UI
  - 食材入力フォーム + 提案結果カード (ランキング表示)
  - 在庫一覧 (期限近い順) + 追加・編集・削除
- [ ] **写真アップロード対応**
  - フロント: `<input type="file" accept="image/*">` + 進捗表示
  - バック: `POST /api/inventory/from-photo` — 画像を Vision API or Claude vision で解析 → 食材候補リスト返却 → ユーザー確認 → 在庫追加
  - 注意: 千切りキャベツや見間違えやすいきのこ類は失敗率高い。**テキスト主、写真補助**の UX
- [ ] **消費期限ベースの優先提案** — `/api/recipes/suggest?prefer_expiring=true` で 3 日以内に切れる食材を優先利用するスコアブースト
- [ ] **menu-catalog 145 件まで拡張** — Phase 1 残 TODO の PDF パイプラインを使って一気に追加
- [ ] **COCORO KITCHEN アプリ追加メニュー対応** — `cocoro_added.json` を別ファイルで管理し、catalog ローダで合算
- [ ] 家族数名で実利用開始 (dogfood)

### Phase 3 — 献立計画 + 学習 + マルチエージェント化 (目安 3 週間)

- [ ] **献立計画エージェント** — 数日分 (3〜7日) のメニューを **食材使い回し** + **主菜/副菜/汁物のバランス** で提案
- [ ] **好み学習** — `suggestion_history` に「採用 / スキップ」ボタンを追加し、よく採用されるメニュー / 食材を加点
- [ ] **アレルギー / 嫌いな食材の登録** — Phase 5 のマルチユーザー前提でテーブル設計だけ先に入れる
- [ ] **LangGraph マルチエージェント化** — 仕様書の構成に揃える
  - `inventory-agent`: 在庫把握・期限優先
  - `meal-plan-agent`: 数日献立組立
  - `shopping-agent`: 不足食材リスト生成
  - `coordinator`: 上記を束ねるルートエージェント
- [ ] **買い物リスト出力 (Phase B)** — 「テキスト出力 + LINE 通知」スタート (確認済の方針)
  - `POST /api/shopping/generate` → 不足食材を整形済テキストで返却
  - LINE bot 連携 (stock-analysis-agent の line_client パターンを流用)
  - Shortcuts URL Scheme は Phase 5 で検討
- [ ] **MCP サーバ化** — 仕様書の構成
  - `mcp-hotcook-catalog`: catalog 検索・食材逆引きを MCP として外部公開 (他の Claude Desktop / IDE からも使える)
  - `mcp-inventory`: SQLite (Phase 4 で Firestore) の在庫 CRUD

### Phase 4 — GCP 移行 (目安 3 週間)

- [ ] **Firestore へ在庫データを移行** — `inventory` / `suggestion_history` テーブルを Firestore コレクションに変換するマイグレーションスクリプト
- [ ] **Cloud SQL に menu-catalog をマスター化** — JSON ファイルから移行し、管理画面 (簡易) で更新可能に
- [ ] **GCS に食材写真 / レシピ画像を保存** — 署名付き URL での配信
- [ ] **Secret Manager で API Keys 管理** — `CLAUDE_CODE_OAUTH_TOKEN` / 各種 API キー
- [ ] **Cloud Run へデプロイ** — Dockerfile を multi-stage 化 + min-instances=0
- [ ] **Firebase Auth 導入** — Web UI から ID トークン → バックで検証
- [ ] **dev/prod 環境分離** — `.env.dev` / `.env.prod` + Cloud Run 別サービス
- [ ] **CI/CD** — kanie-lab-agent のパイプラインを流用 (Cloud Build → Cloud Run)
- [ ] **MCP Sidecar の必要性再評価** — Phase 3 で導入した MCP サーバが本当に GCE sidecar 必須か (多くは Cloud Run 1 サービスに同居可能)

### Phase 5 — マルチユーザー対応 (目安 4 週間)

- [ ] **家族メンバー別の好み** — `users` / `user_preferences` テーブル (Firestore)
- [ ] **共有冷蔵庫モデル** — 1 つの `household` に複数 `users` が紐づく構造 (lifeplanner-agent の `household_id` パターンを流用可能)
- [ ] **アレルギー登録** — **要配慮個人情報**として暗号化保存 + アクセス制御
- [ ] **FCM 通知** — 「今夜の献立提案 (期限切れ間近の食材を活用)」を 17:00 に Push
- [ ] **iOS Shortcuts URL Scheme 連携** — 買い物リストを Reminders に転送する Shortcut テンプレート提供 (Phase 3 の「テキスト出力」より進んだ UX)
- [ ] **Web UI のロール別表示** — 親モード (献立決定) / 子モード (希望リクエスト) の権限分離

### Phase 6 — 高度化 (目安: 機能ごとに独立、優先度低)

- [ ] **栄養素の精密計算** — 文部科学省 食品成分表 DB (オープンデータ) を取り込んで PFC バランス・カロリー算出
- [ ] **買い物自動発注** — 楽西友 / Amazon Fresh 連携 (公式 API があれば、なければ Phase 5 の買い物リスト生成までで止める)
- [ ] **COCORO KITCHEN API 調査** — 公式公開ステータスを定期確認。**非公式リバースエンジニアリングは推奨しない** (利用規約違反リスク)
- [ ] **mcp-recipe-search** — 楽天レシピ API 連携 (ホットクック非対応レシピでも「フライパンの方が早い」判断材料に)。Cookpad API は B2B 限定で対象外
- [ ] **mcp-image-recognition** — Phase 2 の写真在庫認識を MCP 化して他エージェントからも呼べるように

---

## Phase 1 で提供する機能

### API エンドポイント

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/healthz` | ヘルスチェック |
| POST | `/api/recipes/suggest` | 食材リストからメニュー提案 (ランキング) |
| GET | `/api/inventory` | 在庫一覧 (期限近い順 + 更新新しい順) |
| POST | `/api/inventory` | 在庫追加 |
| PUT | `/api/inventory/{id}` | 在庫更新 |
| DELETE | `/api/inventory/{id}` | 在庫削除 |

### POST /api/recipes/suggest

```json
{
  "ingredients": [
    {"name": "じゃがいも"},
    {"name": "牛肉"},
    {"name": "玉ねぎ"}
  ],
  "top_n": 5,
  "max_cook_minutes": 60,
  "require_reservation": false,
  "require_no_mixer": false,
  "mode": "fast"
}
```

| フィールド | 説明 |
|---|---|
| `ingredients[]` | 食材名 (必須・1つ以上)。表記ゆれは ingredient_resolver で吸収 |
| `top_n` | 上位何件返すか (1〜20) |
| `max_cook_minutes` | この時間以内のメニューに絞る |
| `require_reservation` | 予約調理可能なメニューのみ |
| `require_no_mixer` | まぜ技ユニット不要メニューのみ |
| `mode` | `fast` (ルールベース) / `agent` (Claude 補強、**Phase 1 残 TODO のため未実装**。指定しても fast と同じ挙動) |

レスポンスは `candidates[]` がスコア降順にランキングされ、各候補に **食材マッチ詳細・根拠テキスト・公式参照リンク** が付与されます。手順や分量は応答に含めません (著作権配慮)。

### スコアリング (0〜100点)

| 指標 | 配点 |
|---|---|
| 食材タグマッチ率 | 50 |
| 主材料カバレッジ | 20 |
| 調理時間 (短いほど良) | 15 |
| 予約調理可能 | 10 |
| まぜ技ユニット要否一致 | 5 (require_no_mixer 時のみ) |

---

## ディレクトリ構成

```
hotcook-agent/
├── app/
│   ├── main.py                  # FastAPI アプリ
│   ├── config.py                # 環境変数読込
│   ├── agents/
│   │   ├── recipe_suggester.py  # ルールベース提案エンジン
│   │   └── ingredient_resolver.py  # 食材表記ゆれの正規化
│   ├── models/
│   │   ├── menu.py              # HotcookMenu / MenuCatalog
│   │   └── recipe.py            # SuggestRequest/Response, InventoryItem
│   ├── services/
│   │   ├── menu_catalog.py      # menu-catalog.json ローダ + 逆引き
│   │   └── database.py          # SQLite (inventory / suggestion_history)
│   ├── routes/
│   │   ├── recipes.py           # POST /api/recipes/suggest
│   │   └── inventory.py         # 在庫 CRUD
│   └── instrumentation/         # analytics-platform 連携
├── data/
│   ├── skills/
│   │   └── hotcook-recipes/
│   │       ├── SKILL.md                # agent モード用ガイドライン
│   │       ├── menu-catalog.json       # 30 メニュー (Phase 1 シード)
│   │       ├── ingredient-mapping.md
│   │       └── cooking-rules.md
│   ├── local/                   # SQLite DB (.gitignore)
│   └── analytics/               # JSONL 出力先 (.gitignore)
├── scripts/
│   └── seed_menu_catalog.py     # 30 件をリテラルから JSON 生成
├── tests/                       # 82 件
├── pyproject.toml
├── Dockerfile / docker-compose.yml / Makefile
└── .env.example
```

---

## menu-catalog.json (Phase 1 シード)

シャープ公式メニューサイト / 取扱説明書から **事実情報のみ** を抽出した 30 件のキュレーションシード。
カテゴリ内訳:

| カテゴリ | 件数 |
|---|---|
| 煮物 (和風) | 6 |
| カレー・シチュー | 5 |
| スープ | 5 |
| 蒸し料理 | 4 |
| 麺・米 | 3 |
| 発酵・低温調理 | 4 |
| 副菜 | 3 |
| **合計** | **30** |

各エントリのフィールド:

| フィールド | 例 | 説明 |
|---|---|---|
| `menu_no` | `"001"` | シャープ公式番号 |
| `name` | `"肉じゃが"` | メニュー名 |
| `category` | `"nimono"` | スキーマ定義カテゴリ |
| `cook_minutes` | `35` | 標準調理時間 |
| `reservation_ok` | `true` | 予約調理可否 |
| `mixer_required` | `true` | まぜ技ユニット必要か |
| `serves` | `4` | 標準人数 |
| `main_ingredients` | `["じゃがいも", "牛肉", "玉ねぎ"]` | 主材料 (人間可読) |
| `ingredient_tags` | `["jagaimo", "gyuniku", "tamanegi"]` | 正規化タグ (検索キー) |
| `official_source` | `"KN-HW24H 取扱説明書"` | 出典 |
| `verified` | `false` | 人手照合済みフラグ |

**手順 / 分量 / 写真は格納しない**。応答時は `official_source` を返してユーザーが原典に当たれるようにする。

### 再生成

```bash
make seed
```

`scripts/seed_menu_catalog.py` の `SEED_MENUS` を編集して再実行すると `data/skills/hotcook-recipes/menu-catalog.json` が上書きされます。

### 拡張パス

- ユーザーが手元の取扱説明書を見て修正・追加 (PR レビュー)
- Phase 2 で COCORO KITCHEN アプリ追加メニューを `cocoro_added.json` として別ファイル
- Phase 6 で PDF → JSON 構造化パイプライン (`scripts/extract_menu_pdf.py`) を整備

---

## 食材正規化 (ingredient_resolver)

ユーザー入力の表記ゆれを吸収して `ingredient_tags` に変換します。

例:
- `じゃがいも` / `ジャガイモ` / `じゃが芋` / `馬鈴薯` / `potato` / `★じゃがいも(冷蔵)★` → `jagaimo`
- 鶏もも・鶏むね・鶏ささみ → `toriniku` (Phase 1 は粗粒度、Phase 3 で部位別細分化を検討)

詳細は [`data/skills/hotcook-recipes/ingredient-mapping.md`](data/skills/hotcook-recipes/ingredient-mapping.md)。

---

## 環境変数

| 変数名 | 必須 | 説明 |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | - | Phase 2 で agent モードを使うとき必須 |
| `GOOGLE_CLOUD_PROJECT` | - | VertexAI 経由で Claude を使う場合 |
| `VERTEX_AI_LOCATION` | - | デフォルト `us-east5` |
| `APP_ENV` | - | `local` / `dev` / `prod` |
| `LOG_LEVEL` | - | `debug` / `info` / `warning` |
| `DB_PATH` | - | デフォルト `data/local/hotcook.db` |
| `MENU_CATALOG_PATH` | - | デフォルト `data/skills/hotcook-recipes/menu-catalog.json` |
| `ANALYTICS_ENABLED` | - | `false` で JSONL 出力を無効化 (デフォルト `true`) |
| `ANALYTICS_DATA_DIR` | - | デフォルト `./data/analytics` |
| `ANALYTICS_SERVICE_NAME` | - | デフォルト `hotcook-agent` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | - | Phoenix / Langfuse OTLP HTTP |

---

## 分析基盤 (analytics-platform) への送信情報

リクエストごとに以下のイベントを `ANALYTICS_DATA_DIR/raw/service_name=hotcook-agent/event_type=*/dt=YYYY-MM-DD/hour=HH/*.jsonl` に書き出します。

| event_type | 発火タイミング | 件数 |
|---|---|---|
| `conversation_event` | リクエスト開始 / 終了 / 中断 | 2 |
| `business_event` (action=`recipe_suggested`) | `/api/recipes/suggest` 完了時 | 1 |
| `error_event` | 例外発生時 | 0 or 1 |

`recipe_suggested` の `attributes`:
- `ingredient_count` / `top_n` / `mode` / `max_cook_minutes`
- `require_reservation` / `require_no_mixer`
- `candidates_returned` / `top_menu_nos`
- `fallback_used` (該当メニュー無し時)

> ユーザー入力の生文字列はハッシュ化 (`initial_query_hash`) して送信。食材名そのものは business_event の attributes には載せず、`top_menu_nos` のみ。

---

## セットアップ

### 前提

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker & Docker Compose (Docker 起動の場合)

### ローカル起動

```bash
cd hotcook-agent

# 依存インストール + 30 メニュー JSON 生成
make install
make seed

# uvicorn 起動
make run
# → http://localhost:8002
```

### Docker Compose 起動

```bash
cp .env.example .env
make dev
```

### テスト

```bash
make test       # 通常実行
make test-cov   # カバレッジ付き
```

---

## 使用例

### レシピ提案

```bash
curl -X POST http://localhost:8002/api/recipes/suggest \
  -H "Content-Type: application/json" \
  -d '{
        "ingredients": [
          {"name": "じゃがいも"},
          {"name": "牛肉"},
          {"name": "玉ねぎ"}
        ],
        "top_n": 3
      }' | jq
```

### 30 分以内 + 予約調理可能のみ

```bash
curl -X POST http://localhost:8002/api/recipes/suggest \
  -H "Content-Type: application/json" \
  -d '{
        "ingredients": [{"name":"豚肉"},{"name":"大根"}],
        "max_cook_minutes": 30,
        "require_reservation": true
      }'
```

### 在庫追加

```bash
curl -X POST http://localhost:8002/api/inventory \
  -H "Content-Type: application/json" \
  -d '{"name":"じゃがいも","quantity":3,"unit":"個","expires_on":"2026-05-15"}'
```

---

## 制約と将来の方向性

### Phase 1 で割り切ったこと

- **詳細手順 / 分量は格納しない** (著作権配慮)
- **画像認識は対象外** (Phase 2 以降)
- **ホットクックの実機制御は対象外** (COCORO KITCHEN API 非公開)
- **栄養素の精密計算は対象外** (Phase 6)
- **カタログは 30 件** (Phase 2 で 145 件まで拡張)

### 設計上の重要な判断 (詳細はチームで確認済み)

1. **シャープ公式 PDF からの構造化は事実情報のみ** に限定
2. **iOS Reminders 連携は Phase 3 で「テキスト出力 + LINE 通知」スタート** (Shortcuts URL は将来検討)
3. **LangGraph は Phase 3 (マルチエージェント化) から導入** (Phase 1 は単純フロー)
4. **MCP Sidecar (GCE) は Phase 4 で必要性を再評価** (まずは Cloud Run で完結する想定)
