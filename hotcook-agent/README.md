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

| Phase | 内容 | ステータス |
|---|---|---|
| **A (Phase 1)** | ローカル MVP — 食材入力 → ホットクックメニュー提案 (ルールベース) | ✅ **本 PR** |
| B (Phase 2) | Web UI + 在庫管理 (写真アップロード / Next.js) | 未着手 |
| C (Phase 3) | 献立計画 + 学習 + LangGraph によるマルチエージェント化 | 未着手 |
| D (Phase 4) | GCP 移行 (Cloud Run + Firestore + Firebase Auth) | 未着手 |
| E (Phase 5) | マルチユーザー対応 (家族別好み / FCM 通知) | 未着手 |
| F (Phase 6) | 高度化 (栄養計算 / 買い物自動発注 / COCORO KITCHEN API 調査) | 未着手 |

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
| `mode` | `fast` (ルールベース) / `agent` (Claude 補強・Phase 2 以降) |

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
