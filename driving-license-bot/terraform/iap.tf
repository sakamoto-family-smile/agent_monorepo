# Phase 2-C3: IAP IAM bindings — review-admin-ui へのアクセス許可。
#
# Cloud Run direct IAP (HTTPS LB なし) の場合、IAP のアクセス許可は Cloud Run
# service の IAM policy に `roles/iap.httpsResourceAccessor` を付与する形で行う。
# google provider は専用 resource (google_iap_web_cloud_run_service_iam_member)
# を提供していない (2026-04 時点) ため、汎用の
# google_cloud_run_v2_service_iam_member 経由で iap role を付与する。
#
# 事前条件:
# - OAuth consent screen が project で configure 済 (Console で 1 度だけ。docs/SETUP.md §6.5)
# - admin_ui.tf で Cloud Run service が iap_enabled=true で deploy 済
#
# allowlist 外のユーザーは IAP のログイン後にも 403 になる (fail-closed)。
# さらにアプリ層の auth.py で `ADMIN_ALLOWED_EMAILS` も照合 (二段防御)。

resource "google_cloud_run_v2_service_iam_member" "admin_ui_iap_accessor" {
  for_each = local.deploy_admin_ui ? toset(var.review_admin_allowed_emails) : toset([])

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.admin_ui[0].name
  role     = "roles/iap.httpsResourceAccessor"
  member   = "user:${each.value}"

  depends_on = [google_project_service.iap]
}
