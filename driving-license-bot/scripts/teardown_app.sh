#!/usr/bin/env bash
# 課金リソース（Cloud Run / Firestore / Artifact Registry / line-bot SA）
# だけ削除する。WIF / tfstate バケット / API 有効化 / **Secret Manager 枠と値**
# は残すため、再 apply 後に secret 投入し直しが不要になる。
#
# やること:
#   1. Artifact Registry 内の image を全削除（terraform 管理外）
#   2. terraform destroy -target=... で app リソースのみ destroy
#      （Secret 枠と関連 IAM binding は -target に含めない → 残る）
#
# 完全削除（Secret や WIF も消す）したい場合は teardown.sh を使う。
#
# 使い方:
#   make teardown-app
#   または: GOOGLE_CLOUD_PROJECT=sakamomo-family-agent ./scripts/teardown_app.sh

set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:?GOOGLE_CLOUD_PROJECT is required}"
REGION="${REGION:-asia-northeast1}"
REPO="${ARTIFACT_REPO:-driving-license-bot}"
TF_DIR="$(dirname "$0")/../terraform"

echo "[teardown_app] project=${PROJECT} region=${REGION}"
echo "[teardown_app] このスクリプトは app リソースのみ削除します。"
echo "[teardown_app]   - Cloud Run / Firestore / Artifact Registry / sa-line-bot は削除"
echo "[teardown_app]   - WIF / tfstate / API / Secret 枠と値 は残す（再投入不要）"
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

# 2. app リソースのみ terraform destroy。-target で WIF / tfstate / API / Secret を保護。
echo "[teardown_app] running terraform destroy on app resources ..."
cd "${TF_DIR}"
terraform destroy -auto-approve \
    -target=google_cloud_run_v2_service.line_bot \
    -target=google_cloud_run_v2_service_iam_member.line_bot_invoker \
    -target=google_firestore_database.default \
    -target=google_artifact_registry_repository.main \
    -target=google_service_account.line_bot \
    -target=google_project_iam_member.line_bot_datastore_user \
    -target=google_project_iam_member.line_bot_log_writer \
    -target=google_project_iam_member.line_bot_metric_writer
# NOTE: Secret 関連 (google_secret_manager_secret.* と _iam_member.line_bot_*)
# はあえて -target に含めない → 値が消えないので make tf-apply 後に再投入不要。
# Secret に紐づく sa-line-bot accessor binding も残るが、SA 不在中は orphan として
# 安全（次の tf-apply で SA 復活時に同じ email で binding が有効化される）。

cat <<'DONE'

[teardown_app] done. 削除されたもの:

  - Cloud Run service (line-bot-service)
  - Firestore database
  - Artifact Registry repo + image
  - sa-line-bot SA + project-level IAM 3 件

[teardown_app] 残っているもの:

  CI 用:
  - WIF Pool / Provider
  - sa-terraform-plan SA + IAM
  - tfstate バケット
  - 有効化済み API

  Secret（値ごと残るので再投入不要）:
  - driving-license-bot-line-channel-secret
  - driving-license-bot-line-channel-access-token
  - driving-license-bot-line-login-channel-secret
  - driving-license-bot-operator-line-user-ids

→ `Terraform plan / driving-license-bot` ジョブは引き続き動作します。
→ 再展開: `make tf-apply`（secret は既存値が再利用される）
→ Secret も消したい完全削除: `make teardown`
DONE
