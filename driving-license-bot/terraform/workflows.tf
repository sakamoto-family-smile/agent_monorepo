# Phase 2-B2: Cloud Workflow が driving-license-bot-batch Job を起動する。
#
# yaml の中身は workflows/generation_pipeline.yaml に定義済み。terraform は
# それを source_contents として渡すだけ。yaml 編集後の差分も terraform plan で
# 検知できる。

resource "google_workflows_workflow" "generation_pipeline" {
  count = local.deploy_batch ? 1 : 0

  project         = var.project_id
  region          = var.region
  name            = local.workflow_name
  description     = "Run question generation batch via Cloud Run Job."
  service_account = local.sa_workflow_email
  source_contents = file("${path.module}/../workflows/generation_pipeline.yaml")
  labels          = local.labels

  # Provider 6.x で default true。dev/PoC では teardown を妨げないよう
  # var.deletion_protection (既定 false) に追従。
  deletion_protection = var.deletion_protection

  depends_on = [
    google_project_service.workflows,
    google_project_iam_member.workflow_run_invoker,
    google_service_account_iam_member.workflow_act_as_batch,
    google_cloud_run_v2_job.batch,
  ]
}
