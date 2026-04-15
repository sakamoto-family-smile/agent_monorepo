# 蟹江研究室 大学院入試準備エージェント

慶應義塾大学大学院 政策・メディア研究科 蟹江憲史研究室への入学を目指すユーザーを支援する、AIリサーチ・アシスタントのWebアプリケーションです。

## 概要

### 対象ユーザー

慶應SFC・政策メディア研究科 蟹江憲史研究室への大学院入学を目指す志願者。

### 主な機能

1. **研究テーマ設計支援** - SDGs・環境政策・子ども政策の研究テーマ検討
2. **論文サーベイ支援** - 学術データベースを横断した体系的な文献調査
3. **面接対策** - 研究計画の模擬面接と厳格なフィードバック
4. **研究計画レビュー** - 7軸評価による研究計画の改善支援

### 技術スタック

| レイヤー | 技術 |
|---------|------|
| フロントエンド | Next.js 15 / React 19 / TypeScript / Tailwind CSS |
| バックエンド | Python 3.12 / FastAPI / Claude Agent SDK |
| AI | Claude Sonnet (claude-sonnet-4-6) |
| 認証 | Firebase Authentication |
| データベース | Cloud Firestore |
| MCPツール | Google Search, Brave Search, Paper Search, arXiv, Semantic Scholar, e-Stat, e-Gov |

---

## セットアップ手順（ローカル開発）

### 前提条件

- Docker Desktop がインストールされていること
- Node.js 20+ がインストールされていること（Firebase CLI用）
- Anthropic API キーを持っていること

### 1. リポジトリのクローン

```bash
git clone <repository-url>
cd kanie-lab-agent
```

### 2. 環境変数の設定

```bash
cp .env.example .env
```

`.env` を編集して以下を設定：

```env
# 必須
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxx

# 任意（あると機能が拡張される）
BRAVE_API_KEY=BSA_xxxxxxxx          # Brave Search API
ESTAT_APP_ID=xxxxxxxx               # e-Stat API
GOOGLE_CLOUD_PROJECT=your-project   # Google Cloud（Google Search用）
```

#### APIキーの取得方法

**Anthropic API Key（必須）**
1. https://console.anthropic.com/ にアクセス
2. アカウント作成後、「API Keys」から発行

**Brave Search API Key（任意・無料枠 2,000回/月）**
1. https://brave.com/search/api/ にアクセス
2. "Get started for free" からアカウント作成
3. ダッシュボードの「API Keys」から発行

**e-Stat アプリケーションID（任意・無料・無制限）**
1. https://www.e-stat.go.jp/api/ にアクセス
2. 「ユーザ登録」からアカウント作成
3. ログイン後「マイページ」→「API機能」→「アプリケーションID発行」から取得

### 3. Firebase Emulator のセットアップ

```bash
# Firebase CLI をインストール（未インストールの場合）
npm install -g firebase-tools

# Firebase にログイン（初回のみ）
firebase login

# Emulator を起動
cd infra/firebase
firebase emulators:start --only auth,firestore --project demo-kanie-lab
```

### 4. Docker Compose で起動

```bash
docker compose up --build
```

### 5. アクセス

| サービス | URL |
|---------|-----|
| フロントエンド | http://localhost:3000 |
| バックエンドAPI | http://localhost:8000 |
| APIドキュメント | http://localhost:8000/docs |
| Firebase Emulator UI | http://localhost:4000 |

---

## GCP デプロイ手順

### 前提条件

- `gcloud` CLI インストール済み・ログイン済み（`gcloud auth login`）
- GCP プロジェクト作成済み
- Firebase プロジェクト作成済み（Auth + Firestore 有効化済み）
- Firebase Console で **Authentication → Sign-in method → メール/パスワード** を有効化済み
- GitHub リポジトリにコードをプッシュ済み
- Docker Desktop 起動済み

### Step 1: GCP 初期セットアップ（初回のみ）

```bash
export PROJECT_ID=your-gcp-project-id
export REGION=us-central1   # 省略時: us-central1

make setup-gcp
```

対話形式で以下を一括処理します：

| 処理 | 内容 |
|------|------|
| GCP リソース作成 | Artifact Registry / サービスアカウント / IAM / Secret Manager / Firestore |
| シークレット登録 | Anthropic API キー / Claude 認証情報 / Brave / e-Stat / Firebase 設定 |
| CI/CD 設定 | Cloud Build トリガー（GitHub 連携） |

入力が必要な情報：
- Anthropic API キー（必須）
- Firebase 本番設定（Firebase Console → プロジェクト設定 → Web アプリから取得）
- GitHub オーナー名 / リポジトリ名

### Step 2: 初回デプロイ

```bash
make first-deploy
```

以下を自動で実行します（約15分）：

1. バックエンド Docker イメージをビルド＆プッシュ
2. フロントエンド Docker イメージをビルド＆プッシュ
3. バックエンドを Cloud Run にデプロイ
4. フロントエンドを Cloud Run にデプロイ
5. フロントエンド URL を Secret Manager に自動登録 → バックエンドを再デプロイ（CORS 設定反映）

完了後、フロントエンド URL が表示されます：
```
https://kanie-lab-frontend-XXXXXXXXXX-uc.a.run.app
```

### 以降の更新デプロイ

```bash
git push origin main
# → Cloud Build トリガーが自動でビルド＆デプロイ
```

### カスタムドメインの設定（任意）

```bash
gcloud run domain-mappings create \
  --service=kanie-lab-frontend \
  --domain=agent.yourdomain.com \
  --region=${REGION}
```

---

## GCP 環境の削除手順

### リソースの一括削除

```bash
export PROJECT_ID=your-gcp-project-id
export REGION=us-central1

make destroy
```

実行すると確認プロンプトが表示されます。`yes` を入力すると以下を削除します：

| # | リソース |
|---|---------|
| 1 | Cloud Run サービス（backend / frontend） |
| 2 | Artifact Registry リポジトリ（Docker イメージごと） |
| 3 | Secret Manager シークレット（全6件） |
| 4 | サービスアカウント（IAM 権限も自動解除） |
| 5 | Cloud Build トリガー |

### Firestore の削除（手動）

Firestore は CLI での削除に制約があるため、手動で行います：

Firebase Console → [Firestore](https://console.firebase.google.com/) → 「データを削除」→「データベースを削除」

### プロジェクトごと全削除する場合

```bash
gcloud projects delete your-gcp-project-id
```

上記の手順は不要になります（プロジェクト内のリソースがすべて削除されます）。

---

## 開発ガイド

### バックエンドのみ起動

```bash
cd backend
pip install -e .
uvicorn main:app --reload
```

### フロントエンドのみ起動

```bash
cd frontend
npm install
npm run dev
```

### テスト

```bash
# バックエンドAPIのヘルスチェック
curl http://localhost:8000/health

# チャットAPIのテスト（エミュレーター環境）
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer demo-local-user" \
  -d '{"message": "SDGsの研究テーマを考えたい", "mode": "research"}'
```

---

## ディレクトリ構造

```
kanie-lab-agent/
├── README.md               # このファイル
├── CLAUDE.md               # Claudeエージェントの設定
├── .env.example            # 環境変数テンプレート
├── docker-compose.yml      # Dockerコンテナ設定
├── .claude/
│   └── skills/             # カスタムスキルファイル
│       ├── research-design.md      # 研究テーマ設計
│       ├── interview-practice.md   # 面接対策
│       ├── paper-survey.md         # 論文サーベイ
│       ├── sdgs-analysis.md        # SDGs分析
│       ├── child-policy.md         # 子ども政策
│       ├── social-impl.md          # 社会実装
│       ├── web-research.md         # Web調査
│       └── research-review.md      # 研究計画レビュー
├── backend/                # FastAPI バックエンド
├── tools/                  # カスタムMCPツール
│   └── google-search-mcp/  # Google検索MCPサーバー
├── frontend/               # Next.js フロントエンド
├── cloudbuild.yaml         # Cloud Build CI/CD パイプライン
├── Makefile                # 開発・デプロイコマンド集
└── infra/                  # インフラ設定
    ├── docker/             # Dockerfile（開発用・本番用）
    ├── firebase/           # Firebase Emulator 設定
    ├── cloudrun/           # Cloud Run サービス定義
    └── scripts/            # セットアップ・削除スクリプト
```

---

## 使い方

### モードの選択

アプリには4つのモードがあります：

| モード | 説明 |
|-------|------|
| 研究テーマ設計 | SDGs・環境政策の研究テーマを一緒に考える |
| 論文サーベイ | 学術データベースを横断して文献を調査する |
| 面接対策 | 模擬面接で厳しめのフィードバックを受ける |
| 研究計画レビュー | 7軸評価で研究計画を改善する |

### 典型的な使用フロー

1. ログイン（メールアドレス＋パスワード）
2. モードを選択
3. 質問・相談を入力
4. エージェントが論文・政策文書を検索しながら回答
5. セッションは自動保存される

---

## ライセンス

MIT License
