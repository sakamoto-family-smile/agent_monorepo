# terraform state を sakamomo-family-agent の共有 state バケットに置く。
# prefix で driving-license-bot / fujisawa-platform / piyolog と分離。

terraform {
  backend "gcs" {
    bucket = "sakamomo-family-agent-tfstate"
    prefix = "fujisawa-info-bot/terraform"
  }
}
