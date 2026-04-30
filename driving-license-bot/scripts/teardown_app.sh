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
echo "[teardown_app]   - destroy 前に Firestore + Cloud SQL を GCS にバックアップ"
echo "[teardown_app]   - Cloud Run / Firestore / Artifact Registry / sa-line-bot は削除"
echo "[teardown_app]   - Cloud SQL instance (\$10/月) も削除（再 apply 後 make restore で復元）"
echo "[teardown_app]   - WIF / tfstate / API / Secret 枠 / backup bucket は残す"
read -r -p "[teardown_app] よろしいですか？ (yes/no): " CONFIRM
if [[ "${CONFIRM}" != "yes" ]]; then
    echo "[teardown_app] aborted"
    exit 1
fi

# 0. destroy 前に Firestore + Cloud SQL を GCS にバックアップ (Phase 2-Y1)
#    backup 失敗時はユーザーに確認 (継続するかは判断)
echo "[teardown_app] running backup_data.sh ..."
if ! "$(dirname "$0")/backup_data.sh"; then
    echo "[teardown_app] WARN: backup 失敗。データ消失のリスクあり。" >&2
    read -r -p "[teardown_app] それでも続行しますか？ (yes/no): " CONFIRM2
    if [[ "${CONFIRM2}" != "yes" ]]; then
        echo "[teardown_app] aborted"
        exit 1
    fi
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
    -target=google_project_iam_member.line_bot_metric_writer \
    -target=google_sql_user.app \
    -target=google_sql_database.question_bank \
    -target=google_sql_database_instance.main \
    -target=google_secret_manager_secret_version.cloudsql_password \
    -target=random_password.cloudsql_app \
    -target=google_service_account.batch \
    -target=google_project_iam_member.batch_aiplatform_user \
    -target=google_project_iam_member.batch_cloudsql_client \
    -target=google_project_iam_member.batch_datastore_user \
    -target=google_project_iam_member.batch_log_writer \
    -target=google_project_iam_member.batch_metric_writer \
    -target=google_secret_manager_secret_iam_member.batch_cloudsql_password \
    -target=google_secret_manager_secret_iam_member.batch_line_channel_access_token \
    -target=google_secret_manager_secret_iam_member.batch_line_channel_secret \
    -target=google_secret_manager_secret_iam_member.batch_operator_user_ids \
    -target=google_service_account.workflow \
    -target=google_project_iam_member.workflow_run_invoker \
    -target=google_project_iam_member.workflow_log_writer \
    -target=google_service_account_iam_member.workflow_act_as_batch \
    -target=google_service_account.scheduler \
    -target=google_project_iam_member.scheduler_workflows_invoker \
    -target=google_cloud_scheduler_job.batch_nightly \
    -target=google_workflows_workflow.generation_pipeline \
    -target=google_cloud_run_v2_job.batch \
    -target=google_cloud_run_v2_service_iam_member.admin_ui_iap_accessor \
    -target=google_cloud_run_v2_service.admin_ui \
    -target=google_service_account.admin_ui \
    -target=google_project_iam_member.admin_ui_cloudsql_client \
    -target=google_project_iam_member.admin_ui_datastore_user \
    -target=google_project_iam_member.admin_ui_log_writer \
    -target=google_project_iam_member.admin_ui_metric_writer \
    -target=google_secret_manager_secret_iam_member.admin_ui_cloudsql_password
# NOTE: LINE 系の Secret (google_secret_manager_secret.line_*) と
# google_secret_manager_secret.cloudsql_password の「枠」はあえて -target に含めない
# → LINE token は次回 apply 後に再投入不要、cloudsql-password の枠も残るが値は次回
#   apply で random_password が再生成されて上書きされる（DB 自体が新規生成のため整合）。
# Secret に紐づく sa-line-bot accessor binding も残るが、SA 不在中は orphan として
# 安全（次の tf-apply で SA 復活時に同じ email で binding が有効化される）。

cat <<'DONE'

[teardown_app] done. 削除されたもの:

  - Cloud Run service (line-bot-service)
  - Firestore database
  - Artifact Registry repo + image
  - sa-line-bot SA + project-level IAM 3 件
  - Cloud SQL instance + question_bank database + app user
  - cloudsql-password secret value（枠は残る、次回 apply で random_password 再生成）
  - sa-batch / sa-workflow / sa-scheduler SA + 各 IAM binding
  - Cloud Run Job (driving-license-bot-batch)
  - Cloud Workflow (generation-pipeline)
  - Cloud Scheduler (batch-nightly)
  - Cloud Run service (driving-license-bot-admin-ui)
  - sa-admin-ui SA + IAM 5 件
  - IAP IAM bindings (allowed_emails)

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

  Secret 枠のみ（値は次回 apply で再生成）:
  - driving-license-bot-cloudsql-password

→ `Terraform plan / driving-license-bot` ジョブは引き続き動作します。
→ 再展開: `make tf-apply`（LINE secret は既存値が再利用される）
→ Cloud SQL のデータ復元: `make restore`（destroy 前のバックアップから自動復元）
→ Cloud SQL のスキーマだけ作り直す場合: `make cloudsql-init`
→ Secret も消したい完全削除: `make teardown`
DONE
