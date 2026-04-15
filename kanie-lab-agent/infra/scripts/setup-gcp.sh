#!/bin/bash
# GCP 初期セットアップスクリプト（インタラクティブ版）
# GCP リソース作成 → シークレット登録 → Cloud Build トリガー設定 まで一括実行
#
# 使い方:
#   export PROJECT_ID=your-gcp-project-id
#   export REGION=us-central1           # 省略時: us-central1
#   bash infra/scripts/setup-gcp.sh
#
# 必要な権限: Project Owner または Editor

set -euo pipefail

: "${PROJECT_ID:?環境変数 PROJECT_ID を設定してください}"
: "${REGION:=us-central1}"

BACKEND_SA="kanie-lab-backend@${PROJECT_ID}.iam.gserviceaccount.com"
FRONTEND_SA="kanie-lab-frontend@${PROJECT_ID}.iam.gserviceaccount.com"
CLOUDBUILD_SA="${PROJECT_ID}@cloudbuild.gserviceaccount.com"

# ---- ユーティリティ ----
prompt() {
  local var_name="$1"
  local label="$2"
  local default="${3:-}"
  local is_secret="${4:-false}"

  if [ -n "${default}" ]; then
    printf "  %s [%s]: " "${label}" "${default}"
  else
    printf "  %s: " "${label}"
  fi

  if [ "${is_secret}" = "true" ]; then
    read -rs value
    echo ""
  else
    read -r value
  fi

  if [ -z "${value}" ] && [ -n "${default}" ]; then
    value="${default}"
  fi
  eval "${var_name}='${value}'"
}

secret_add() {
  local name="$1"
  local value="$2"
  if [ -z "${value}" ]; then
    echo "    → スキップ（空のため）"
    return
  fi
  echo -n "${value}" | gcloud secrets versions add "${name}" \
    --data-file=- --project="${PROJECT_ID}" --quiet
  echo "    → 登録しました"
}

# ========================================================================
echo "========================================================"
echo "  🚀 kanie-lab-agent GCP セットアップ"
echo "========================================================"
echo ""
echo "  Project : ${PROJECT_ID}"
echo "  Region  : ${REGION}"
echo ""

gcloud config set project "${PROJECT_ID}"

# ========================================================================
# [1] API の有効化
# ========================================================================
echo "[1/7] API を有効化中..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  firestore.googleapis.com \
  firebase.googleapis.com \
  aiplatform.googleapis.com \
  --project="${PROJECT_ID}"
echo "  ✓ 完了"

# ========================================================================
# [2] Artifact Registry
# ========================================================================
echo "[2/7] Artifact Registry リポジトリを作成中..."
gcloud artifacts repositories create kanie-lab \
  --repository-format=docker \
  --location="${REGION}" \
  --description="kanie-lab-agent Docker images" \
  --project="${PROJECT_ID}" 2>/dev/null || true
echo "  ✓ 完了"

# ========================================================================
# [3] サービスアカウント & IAM
# ========================================================================
echo "[3/7] サービスアカウントと IAM 権限を設定中..."

gcloud iam service-accounts create kanie-lab-backend \
  --display-name="kanie-lab Backend SA" \
  --project="${PROJECT_ID}" 2>/dev/null || true

gcloud iam service-accounts create kanie-lab-frontend \
  --display-name="kanie-lab Frontend SA" \
  --project="${PROJECT_ID}" 2>/dev/null || true

for role in roles/datastore.user roles/secretmanager.secretAccessor \
            roles/aiplatform.user roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${BACKEND_SA}" --role="${role}" --quiet
done

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${FRONTEND_SA}" \
  --role="roles/logging.logWriter" --quiet

for role in roles/run.admin roles/iam.serviceAccountUser \
            roles/artifactregistry.writer roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${CLOUDBUILD_SA}" --role="${role}" --quiet
done

echo "  ✓ 完了"

# ========================================================================
# [4] Firestore
# ========================================================================
echo "[4/7] Firestore を初期化中..."
gcloud firestore databases create \
  --location="${REGION}" \
  --project="${PROJECT_ID}" 2>/dev/null || true
echo "  ✓ 完了"

# ========================================================================
# [5] シークレット作成
# ========================================================================
echo "[5/7] Secret Manager にシークレットを作成中..."
for secret in anthropic-api-key brave-api-key estat-app-id \
              semantic-scholar-api-key frontend-url claude-credentials; do
  gcloud secrets create "${secret}" \
    --project="${PROJECT_ID}" 2>/dev/null || true
done
echo "  ✓ 完了"

# ========================================================================
# [6] シークレット値の入力・登録
# ========================================================================
echo ""
echo "[6/7] シークレットの値を入力してください"
echo "      （スキップする場合は Enter を押してください）"
echo ""

# Anthropic API キー
echo "  --- Anthropic API キー（必須）---"
prompt ANTHROPIC_KEY "API キー (sk-ant-...)" "" "true"
secret_add "anthropic-api-key" "${ANTHROPIC_KEY}"

# Claude 認証情報
echo "  --- Claude OAuth 認証情報 ---"
CLAUDE_CRED_FILE="${HOME}/.claude/credentials.json"
if [ -f "${CLAUDE_CRED_FILE}" ]; then
  printf "  %s を使用しますか？ [Y/n]: " "${CLAUDE_CRED_FILE}"
  read -r use_local
  if [ "${use_local}" != "n" ] && [ "${use_local}" != "N" ]; then
    gcloud secrets versions add "claude-credentials" \
      --data-file="${CLAUDE_CRED_FILE}" --project="${PROJECT_ID}" --quiet
    echo "    → 登録しました"
  fi
else
  echo "  ${CLAUDE_CRED_FILE} が見つかりません。Claude にログインしてから再実行してください。"
fi

# Brave API キー
echo "  --- Brave Search API キー（任意）---"
prompt BRAVE_KEY "API キー (BSA_...)" "" "true"
secret_add "brave-api-key" "${BRAVE_KEY}"

# e-Stat App ID
echo "  --- e-Stat アプリケーション ID（任意）---"
prompt ESTAT_ID "App ID" "" "false"
secret_add "estat-app-id" "${ESTAT_ID}"

# Semantic Scholar
echo "  --- Semantic Scholar API キー（任意）---"
prompt SS_KEY "API キー" "" "true"
secret_add "semantic-scholar-api-key" "${SS_KEY}"

# Firebase 設定
echo ""
echo "  --- Firebase 本番設定 ---"
echo "  Firebase Console → プロジェクト設定 → アプリを追加（Web）から取得してください"
echo ""
prompt FB_PROJECT_ID   "Firebase Project ID" "${PROJECT_ID}"
prompt FB_API_KEY      "Firebase API Key (AIzaSy...)" "" "true"
prompt FB_AUTH_DOMAIN  "Auth Domain" "${PROJECT_ID}.firebaseapp.com"
prompt FB_STORAGE      "Storage Bucket" "${PROJECT_ID}.appspot.com"
prompt FB_SENDER_ID    "Messaging Sender ID" ""
prompt FB_APP_ID       "App ID (1:xxx:web:xxx)" "" ""

# Firebase 設定をファイルに保存（Cloud Build の substitutions 用）
FIREBASE_ENV_FILE="infra/scripts/.firebase-config"
cat > "${FIREBASE_ENV_FILE}" << EOF
FIREBASE_PROJECT_ID=${FB_PROJECT_ID}
FIREBASE_API_KEY=${FB_API_KEY}
FIREBASE_AUTH_DOMAIN=${FB_AUTH_DOMAIN}
FIREBASE_STORAGE_BUCKET=${FB_STORAGE}
FIREBASE_MESSAGING_SENDER_ID=${FB_SENDER_ID}
FIREBASE_APP_ID=${FB_APP_ID}
EOF
echo "  → Firebase 設定を ${FIREBASE_ENV_FILE} に保存しました（gitignore 対象）"

# ========================================================================
# [7] Cloud Build トリガーの作成
# ========================================================================
echo ""
echo "[7/7] Cloud Build トリガーを設定します"
echo ""
prompt GITHUB_OWNER "GitHub オーナー名（org または username）" ""
prompt GITHUB_REPO  "リポジトリ名" "kanie-lab-agent"

if [ -n "${GITHUB_OWNER}" ]; then
  # GitHub リポジトリを Cloud Build に接続済みであることが前提
  gcloud builds triggers create github \
    --name="kanie-lab-deploy-main" \
    --repo-name="${GITHUB_REPO}" \
    --repo-owner="${GITHUB_OWNER}" \
    --branch-pattern='^main$' \
    --build-config=cloudbuild.yaml \
    --substitutions="_REGION=${REGION},_BACKEND_SA=${BACKEND_SA},_FRONTEND_SA=${FRONTEND_SA},_FIREBASE_PROJECT_ID=${FB_PROJECT_ID},_FIREBASE_API_KEY=${FB_API_KEY},_FIREBASE_AUTH_DOMAIN=${FB_AUTH_DOMAIN},_FIREBASE_STORAGE_BUCKET=${FB_STORAGE},_FIREBASE_MESSAGING_SENDER_ID=${FB_SENDER_ID},_FIREBASE_APP_ID=${FB_APP_ID}" \
    --project="${PROJECT_ID}" 2>/dev/null || \
  echo "  トリガーはすでに存在します（値を更新する場合は Cloud Console から編集してください）"
  echo "  ✓ 完了"
else
  echo "  スキップしました（後から make setup-trigger で設定できます）"
fi

# ========================================================================
echo ""
echo "========================================================"
echo "  ✅ セットアップ完了"
echo "========================================================"
echo ""
echo "  次のステップ:"
echo "    make first-deploy   # 初回ビルド＆デプロイ（約15分）"
echo ""
