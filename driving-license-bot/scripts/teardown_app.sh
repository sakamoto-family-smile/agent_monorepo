#!/usr/bin/env bash
# 課金リソース（Cloud Run / Firestore / Secret 枠 / Artifact Registry / line-bot SA）
# だけ削除する。WIF / tfstate バケット / API 有効化は残すため、CI plan は動き続ける。
#
# やること:
#   1. Artifact Registry 内の image を全削除（terraform 管理外）
#   2. terraform destroy -target=... で app リソースのみ destroy
#   3. Secret Manager secret の即時削除
#
# 完全削除（WIF も消す）したい場合は teardown.sh を使う。
#
# 使い方:
#   GOOGLE_CLOUD_PROJECT=sakamomo-family-agent ./scripts/teardown_app.sh

set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:?GOOGLE_CLOUD_PROJECT is required}"
REGION="${REGION:-asia-northeast1}"
REPO="${ARTIFACT_REPO:-driving-license-bot}"
TF_DIR="$(dirname "$0")/../terraform"

echo "[teardown_app] project=${PROJECT} region=${REGION}"
echo "[teardown_app] このスクリプトは app リソースのみ削除します（WIF / tfstate / API は残す）。"
echo "[teardown_app] CI の terraform plan ジョブは継続して動作します。"
read -r -p "[teardown_app] よろしいですか？ (yes/no): " CONFIRM
if [[ "${CONFIRM}" != "yes" ]]; then
    echo "[teardown_app] aborted"
    exit 1
fi

# 1. Artifact Registry の image を全削除
echo "[teardown_app] purging Artifact Registry images ..."
if gcloud artifacts repositories describe "${REPO}" \
    --project="${PROJECT}" --location="${REGION}" >/dev/null 2>&1; then
    gcloud artifacts docker images list "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}" \
        --include-tags --format='value(IMAGE,DIGEST)' 2>/dev/null \
        | while read -r IMG DIGEST; do
            [[ -z "${IMG}" ]] && continue
            echo "  deleting ${IMG}@${DIGEST}"
            gcloud artifacts docker images delete "${IMG}@${DIGEST}" --quiet --delete-tags || true
        done
fi

# 2. app リソースのみ terraform destroy。-target で WIF / tfstate / API を保護。
echo "[teardown_app] running terraform destroy on app resources ..."
cd "${TF_DIR}"
terraform destroy -auto-approve \
    -target=google_cloud_run_v2_service.line_bot \
    -target=google_cloud_run_v2_service_iam_member.line_bot_invoker \
    -target=google_firestore_database.default \
    -target=google_secret_manager_secret.line_channel_secret \
    -target=google_secret_manager_secret.line_channel_access_token \
    -target=google_secret_manager_secret.line_login_channel_secret \
    -target=google_secret_manager_secret.operator_user_ids \
    -target=google_secret_manager_secret_iam_member.line_bot_channel_secret \
    -target=google_secret_manager_secret_iam_member.line_bot_channel_access_token \
    -target=google_secret_manager_secret_iam_member.line_bot_operator_user_ids \
    -target=google_artifact_registry_repository.main \
    -target=google_service_account.line_bot \
    -target=google_project_iam_member.line_bot_datastore_user \
    -target=google_project_iam_member.line_bot_log_writer \
    -target=google_project_iam_member.line_bot_metric_writer

# 3. Secret Manager 即時削除（destroy は schedule 付きなので明示削除）
echo "[teardown_app] force-deleting Secret Manager secrets ..."
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

cat <<'DONE'

[teardown_app] done. 削除されたもの:

  - Cloud Run service (line-bot-service)
  - Firestore database
  - Secret Manager 4 secrets
  - Artifact Registry repo + image
  - sa-line-bot SA + IAM bindings

[teardown_app] 残っているもの（CI plan に必要）:

  - WIF Pool / Provider
  - sa-terraform-plan SA + IAM
  - tfstate バケット
  - 有効化済み API

→ `Terraform plan / driving-license-bot` ジョブは引き続き動作します。
→ 再展開する場合: tfvars に line_bot_image を埋めて `make tf-apply`。
→ WIF も含めて完全削除する場合: `make teardown`。
DONE
