# terraform state を共有 state バケットに置く (prefix で他モジュールと分離)。
terraform {
  backend "gcs" {
    bucket = "sakamomo-family-agent-tfstate"
    prefix = "analytics-platform/terraform"
  }
}
