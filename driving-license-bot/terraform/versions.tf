terraform {
  required_version = ">= 1.7.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.45, < 7.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = ">= 5.45, < 7.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # State は GCS で管理する（terraform destroy 時に履歴を残すため）。
  # bucket は事前に手動作成（chicken-and-egg）。手順は terraform/README.md と
  # scripts/bootstrap_gcp.sh 参照。
  # 初回 init 時は backend.tf を別途用意する形でも OK。
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}
