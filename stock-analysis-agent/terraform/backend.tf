# terraform state を sakamomo-family-agent の共有 state バケットに置く。
# prefix で driving-license-bot / fujisawa-* / piyolog / analytics と分離。

terraform {
  backend "gcs" {
    bucket = "sakamomo-family-agent-tfstate"
    prefix = "stock-analysis-agent/terraform"
  }
}
