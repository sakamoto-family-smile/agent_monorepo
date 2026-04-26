terraform {
  required_version = ">= 1.7.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.40"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # State は GCS で管理する。bucket は事前に手動作成 (chicken-and-egg)。
  # 詳細は terraform/README.md の "Bootstrap" を参照。
  # backend "gcs" {
  #   bucket = "<your-project>-tfstate"
  #   prefix = "piyolog-analytics"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
