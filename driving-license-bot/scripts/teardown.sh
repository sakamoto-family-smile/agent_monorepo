#!/usr/bin/env bash
# 一発で driving-license-bot のインフラを削除する。
#
# やること:
#   1. terraform destroy: SA / Firestore / Secret 枠 / Cloud Run / Artifact Registry
#   2. Artifact Registry 内の image を全削除（terraform 管理外のため）
#   3. （任意）tfstate バケット自体は残す。完全初期化したい時は --purge-state で。
#
# 注意:
#   - Secret Manager の destroy は schedule 付きで遅延削除になる
#   - Firestore に書き込んだドキュメントは Terraform からは消えない（DB 自体は消える）
#   - LINE 側の Webhook URL を解除するのは Console で手動対応
#
# 使い方:
#   GOOGLE_CLOUD_PROJECT=sakamoto-family-agent ./scripts/teardown.sh
#   GOOGLE_CLOUD_PROJECT=... PURGE_STATE=true ./scripts/teardown.sh   # tfstate も消す

set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:?GOOGLE_CLOUD_PROJECT is required}"
REGION="${REGION:-asia-northeast1}"
REPO="${ARTIFACT_REPO:-driving-license-bot}"
TFSTATE_BUCKET="${TFSTATE_BUCKET:-${PROJECT}-driving-license-bot-tfstate}"
TF_DIR="$(dirname "$0")/../terraform"

echo "[teardown] project=${PROJECT} region=${REGION}"
echo "[teardown] このスクリプトは driving-license-bot のリソースをほぼすべて削除します。"
read -r -p "[teardown] よろしいですか？ (yes/no): " CONFIRM
if [[ "${CONFIRM}" != "yes" ]]; then
    echo "[teardown] aborted"
    exit 1
fi

# 1. Artifact Registry の image を全削除（Terraform からは repo 自体しか消えない）
echo "[teardown] purging Artifact Registry images ..."
if gcloud artifacts repositories describe "${REPO}" \
    --project="${PROJECT}" --location="${REGION}" >/dev/null 2>&1; then
    # repo 内の package を全列挙して削除
    gcloud artifacts docker images list "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}" \
        --include-tags --format='value(IMAGE,DIGEST)' 2>/dev/null \
        | while read -r IMG DIGEST; do
            [[ -z "${IMG}" ]] && continue
            echo "  deleting ${IMG}@${DIGEST}"
            gcloud artifacts docker images delete "${IMG}@${DIGEST}" --quiet --delete-tags || true
        done
fi

# 2. Terraform destroy
echo "[teardown] running terraform destroy ..."
cd "${TF_DIR}"
terraform destroy -auto-approve

# 3. Secret Manager 即時削除（destroy は schedule 付き、明示的に消す）
echo "[teardown] force-deleting Secret Manager secrets ..."
for s in \
    driving-license-bot-line-channel-secret \
    driving-license-bot-line-channel-access-token \
    driving-license-bot-line-login-channel-secret \
    driving-license-bot-operator-line-user-ids; do
    if gcloud secrets describe "${s}" --project="${PROJECT}" >/dev/null 2>&1; then
        echo "  deleting secret ${s}"
        gcloud secrets delete "${s}" --project="${PROJECT}" --quiet || true
    fi
done

# 4. tfstate バケットを消す場合
if [[ "${PURGE_STATE:-false}" == "true" ]]; then
    echo "[teardown] purging tfstate bucket ${TFSTATE_BUCKET} ..."
    if gcloud storage buckets describe "gs://${TFSTATE_BUCKET}" >/dev/null 2>&1; then
        gcloud storage rm -r "gs://${TFSTATE_BUCKET}" --quiet
    fi
fi

cat <<'DONE'

[teardown] done. 残タスク（手動）:

  - LINE Developers Console で Webhook URL を解除 / アカウントを削除
  - 利用規約・プライバシーポリシーの公開ページを停止（公開済みの場合）
  - Cloud Logging / Monitoring に残るログは保持期間に応じて自動削除
  - billing alert / quota は project ごとに別管理

完全に project ごと消すなら:
  gcloud projects delete <PROJECT_ID>
DONE
