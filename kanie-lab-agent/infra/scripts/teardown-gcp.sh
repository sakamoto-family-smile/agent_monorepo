#!/bin/bash
# GCP 環境削除スクリプト
# setup-gcp.sh で作成したリソースをすべて削除する
#
# 使い方:
#   export PROJECT_ID=your-gcp-project-id
#   export REGION=us-central1
#   bash infra/scripts/teardown-gcp.sh
#
# ⚠️  警告: Firestore のデータも含めてすべて削除されます。
#           本番環境で実行する場合は必ずバックアップを取ってください。

set -euo pipefail

: "${PROJECT_ID:?環境変数 PROJECT_ID を設定してください}"
: "${REGION:=us-central1}"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/kanie-lab"

# ---- 確認プロンプト ----
echo "========================================================"
echo "  ⚠️  GCP 環境削除スクリプト"
echo "========================================================"
echo ""
echo "  Project : ${PROJECT_ID}"
echo "  Region  : ${REGION}"
echo ""
echo "  削除対象:"
echo "    - Cloud Run サービス (kanie-lab-backend, kanie-lab-frontend)"
echo "    - Artifact Registry リポジトリ (kanie-lab)"
echo "    - Secret Manager シークレット (全6件)"
echo "    - サービスアカウント (kanie-lab-backend, kanie-lab-frontend)"
echo "    - Cloud Build トリガー (kanie-lab 関連)"
echo "    - Firestore データベース ⚠️ データが消えます"
echo ""
read -p "本当に削除しますか？ [yes/N]: " confirm
if [ "${confirm}" != "yes" ]; then
  echo "キャンセルしました。"
  exit 0
fi

echo ""
gcloud config set project "${PROJECT_ID}"

# ---- 1. Cloud Run サービスの削除 ----
echo "[1/6] Cloud Run サービスを削除中..."
for service in kanie-lab-backend kanie-lab-frontend; do
  if gcloud run services describe "${service}" --region="${REGION}" --project="${PROJECT_ID}" &>/dev/null; then
    gcloud run services delete "${service}" \
      --region="${REGION}" \
      --platform=managed \
      --project="${PROJECT_ID}" \
      --quiet
    echo "  ✓ ${service} を削除しました"
  else
    echo "  - ${service} は存在しません（スキップ）"
  fi
done

# ---- 2. Artifact Registry リポジトリの削除 ----
echo "[2/6] Artifact Registry リポジトリを削除中..."
if gcloud artifacts repositories describe kanie-lab \
    --location="${REGION}" --project="${PROJECT_ID}" &>/dev/null; then
  gcloud artifacts repositories delete kanie-lab \
    --location="${REGION}" \
    --project="${PROJECT_ID}" \
    --quiet
  echo "  ✓ Artifact Registry リポジトリを削除しました"
else
  echo "  - リポジトリは存在しません（スキップ）"
fi

# ---- 3. Secret Manager シークレットの削除 ----
echo "[3/6] Secret Manager シークレットを削除中..."
for secret in \
  anthropic-api-key \
  brave-api-key \
  estat-app-id \
  semantic-scholar-api-key \
  frontend-url \
  claude-credentials; do
  if gcloud secrets describe "${secret}" --project="${PROJECT_ID}" &>/dev/null; then
    gcloud secrets delete "${secret}" \
      --project="${PROJECT_ID}" \
      --quiet
    echo "  ✓ ${secret} を削除しました"
  else
    echo "  - ${secret} は存在しません（スキップ）"
  fi
done

# ---- 4. サービスアカウントの削除 ----
echo "[4/6] サービスアカウントを削除中..."
for sa in kanie-lab-backend kanie-lab-frontend; do
  SA_EMAIL="${sa}@${PROJECT_ID}.iam.gserviceaccount.com"
  if gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT_ID}" &>/dev/null; then
    gcloud iam service-accounts delete "${SA_EMAIL}" \
      --project="${PROJECT_ID}" \
      --quiet
    echo "  ✓ ${SA_EMAIL} を削除しました"
  else
    echo "  - ${SA_EMAIL} は存在しません（スキップ）"
  fi
done

# ---- 5. Cloud Build トリガーの削除 ----
echo "[5/6] Cloud Build トリガーを削除中..."
TRIGGER_IDS=$(gcloud builds triggers list \
  --project="${PROJECT_ID}" \
  --format='value(id)' \
  --filter='filename=cloudbuild.yaml' 2>/dev/null || true)

if [ -n "${TRIGGER_IDS}" ]; then
  echo "${TRIGGER_IDS}" | while read -r trigger_id; do
    gcloud builds triggers delete "${trigger_id}" \
      --project="${PROJECT_ID}" \
      --quiet
    echo "  ✓ トリガー ${trigger_id} を削除しました"
  done
else
  echo "  - 対象トリガーは存在しません（スキップ）"
fi

# ---- 6. Firestore データベースの削除 ----
echo "[6/6] Firestore データベースを削除中..."
echo "  ⚠️  Firestore の削除は gcloud CLI では直接できません。"
echo "  以下のいずれかで削除してください:"
echo ""
echo "  方法A: Firebase Console から手動削除"
echo "    → https://console.firebase.google.com/project/${PROJECT_ID}/firestore"
echo "    → 「データを削除」→「データベースを削除」"
echo ""
echo "  方法B: gcloud コマンド（プレビュー機能）"
echo "    gcloud firestore databases delete (default) --project=${PROJECT_ID}"
echo ""

# ---- 完了 ----
echo "========================================================"
echo "  ✅ 削除完了"
echo "========================================================"
echo ""
echo "  Cloud Run、Artifact Registry、Secret Manager、"
echo "  サービスアカウント、Cloud Build トリガーを削除しました。"
echo ""
echo "  Firestore は上記の手順で手動削除してください。"
echo ""
echo "  GCP プロジェクト自体を削除する場合:"
echo "    gcloud projects delete ${PROJECT_ID}"
echo ""
