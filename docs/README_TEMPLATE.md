<!--
このファイルをコピーして `<agent>/README.md` に展開する想定の README テンプレ。

凡例:
  [必須] 必ず書く
  [推奨] 該当する場合のみ書く (不要なら節ごと削除可)

設計思想:
  - README は「初見ユーザー / 自分が 1 ヶ月後に戻ってきた時」が読む doc
  - Quickstart で 5 分で動かせる
  - 詳細な設計は docs/DESIGN.md / docs/PROPOSALS/ へリンク
  - 環境変数表は .env.example の補足、フル一覧は .env.example で

順序のルール (上から優先度高):
  1. 1 行説明 + ステータス badge
  2. Quickstart (動かす)
  3. 環境変数 (動かすのに必要な情報)
  4. API / コマンド一覧 (使う)
  5. 運用 / デプロイ (本番に乗せる)
  6. 関連ドキュメント (深く知る)
  7. ライセンス
-->

# <Agent name>

<!--
1-2 段落で何をするエージェントか。冒頭は検索 / GitHub プレビューで
出るので、機能が一目で分かるように。
-->

> **Status**: <!-- Phase 1 MVP / Phase 2 進行中 / Production / Archived 等 -->

---

## [必須] 0. Quickstart

### 0.1 前提

<!-- ツール / バージョン -->

| ツール | バージョン | 備考 |
|---|---|---|
| Python | 3.12+ | `pyproject.toml` で指定 |
| uv | 最新 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| <!-- gcloud / Docker / Node.js などあれば --> | | |

### 0.2 セットアップ

```bash
cd agent_monorepo/<agent-name>

# 1. 環境変数テンプレートをコピー
cp .env.example .env
# → .env を編集して必要なキーを設定

# 2. 依存インストール
make install
```

### 0.3 起動

```bash
make run                 # → http://127.0.0.1:XXXX

# ヘルスチェック
curl http://127.0.0.1:XXXX/health
```

### 0.4 テスト・静的解析

```bash
make test         # pytest
make lint         # ruff check
make format       # ruff format + --fix
make check        # lint + test
```

---

## [推奨] 1. 主要 API

<!-- HTTP API を持つエージェントの場合のみ -->

| メソッド | パス | 用途 |
|---|---|---|
| `GET` | `/health` | ヘルスチェック |
| `POST` | `/api/...` | ... |

詳細は OpenAPI: `http://localhost:XXXX/docs`

---

## [推奨] 2. 主要コマンド

<!-- LINE Bot / CLI を持つエージェントの場合のみ -->

| コマンド | 動作 |
|---|---|
| `/help` | コマンド一覧 |
| ... | ... |

---

## [必須] 3. 環境変数

<!--
全部書くと膨大になるので、主要なもののみ。詳細は .env.example 参照。
-->

| 変数 | 既定 | 用途 |
|---|---|---|
| `APP_ENV` | `local` | `local` / `dev` / `prod` |
| `LOG_LEVEL` | `info` | ログレベル |
| <!-- DB / LLM / 外部 API の主要 env --> | | |

詳細: [`.env.example`](.env.example)

---

## [推奨] 4. 外部連携セットアップ

<!--
LINE Bot / LIFF / Vertex AI など、外部サービス連携が必要な場合の手順。
複数あれば 4.1 / 4.2 / 4.3 と分ける。
-->

### 4.1 LINE Bot

<!-- channel 作成 → secret / token を .env に → webhook URL 登録 -->

### 4.2 LIFF

<!-- LINE Login channel + LIFF app の作成 + ID 設定 -->

---

## [推奨] 5. 運用 / デプロイ

<!--
本番環境にデプロイ可能なエージェントのみ。
詳細手順は docs/DEPLOY.md に切り出す (テンプレ: docs/OPERATIONS_TEMPLATE.md)。
README ではコマンド 1-2 行と link で十分。
-->

```bash
# 例
make tf-apply        # Terraform で Cloud SQL / Cloud Run を作る
make deploy-cloud-run  # image push + Cloud Run deploy
```

詳細: [`docs/DEPLOY.md`](docs/DEPLOY.md) <!-- 該当する場合のみ -->

---

## [必須] 6. 関連ドキュメント

<!--
最低でも DESIGN.md (システム全体設計書) と PROPOSALS/ (機能個別) へのリンク。
-->

- [`docs/DESIGN.md`](docs/DESIGN.md) — システム全体設計 (機能要件 / 非機能要件 / アーキテクチャ / Roadmap / 設計判断)
- [`docs/PROPOSALS/`](../docs/PROPOSALS/) — 機能個別の設計提案 / ADR (モノレポ共通)
- <!-- DEPLOY.md / BACKUP_RESTORE.md / SETTINGS.md / *_ROADMAP.md 等該当するもの -->

---

## [推奨] 7. ライセンス

<!-- 個人プロジェクトなので未公開 / 公開時は MIT 等を明記 -->
