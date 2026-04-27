# Firestore database (default)。Phase 1 の状態保管庫。
# プロジェクトに 1 つだけ。location は一度作ると変更不可。

resource "google_firestore_database" "default" {
  project                 = var.project_id
  name                    = "(default)"
  location_id             = var.firestore_location
  type                    = "FIRESTORE_NATIVE"
  concurrency_mode        = "OPTIMISTIC"
  app_engine_integration_mode = "DISABLED"

  # dev/PoC では false にして terraform destroy で消せるようにする。
  # 本番運用に入るタイミングで true に変更（重要 SOP）。
  deletion_policy = var.deletion_protection ? "ABANDON" : "DELETE"

  depends_on = [google_project_service.firestore]
}
