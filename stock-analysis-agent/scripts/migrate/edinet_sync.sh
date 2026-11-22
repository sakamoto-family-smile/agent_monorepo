#!/bin/bash
# EDINET の書類 cache と Edinetcode.csv を GCS とローカルの間で同期する (PROPOSAL-0013)。
#
#   scripts/migrate/edinet_sync.sh down   # GCS → ローカル (cutover-to-local)
#   scripts/migrate/edinet_sync.sh up     # ローカル → GCS (cutover-to-gcp)
#
# レイアウトは LocalCache / GcsCache で同じ (<root>/<content_type>/<document_id>.<ext>):
#   gs://<bucket>/edinet/...        ⇄ ${STOCK_LOCAL_DATA_DIR}/edinet/...
#   gs://<bucket>/Edinetcode.csv    ⇄ ${STOCK_LOCAL_DATA_DIR}/edinet-code/Edinetcode.csv
# cache は再取得できるので、同期先にしか無いファイルは消さない (rsync は追加・更新のみ)。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROJECT_ID="${PROJECT_ID:-sakamomo-family-agent}"
BUCKET="${EDINET_BUCKET:-stock-analysis-line-edinet}"
DATA_DIR="${STOCK_LOCAL_DATA_DIR:-$PROJECT_DIR/data/local}"
CSV_OBJECT="${EDINET_CODE_CSV_OBJECT:-Edinetcode.csv}"

case "${1:-}" in
  down)
    mkdir -p "$DATA_DIR/edinet" "$DATA_DIR/edinet-code"
    gcloud storage rsync --project "$PROJECT_ID" --recursive "gs://$BUCKET/edinet" "$DATA_DIR/edinet"
    gcloud storage cp --project "$PROJECT_ID" "gs://$BUCKET/$CSV_OBJECT" "$DATA_DIR/edinet-code/Edinetcode.csv"
    ;;
  up)
    [ -f "$DATA_DIR/edinet-code/Edinetcode.csv" ] || { echo "$DATA_DIR/edinet-code/Edinetcode.csv がありません" >&2; exit 1; }
    if [ -d "$DATA_DIR/edinet" ]; then
      gcloud storage rsync --project "$PROJECT_ID" --recursive "$DATA_DIR/edinet" "gs://$BUCKET/edinet"
    fi
    gcloud storage cp --project "$PROJECT_ID" "$DATA_DIR/edinet-code/Edinetcode.csv" "gs://$BUCKET/$CSV_OBJECT"
    ;;
  *)
    echo "usage: $0 {down|up}" >&2; exit 2
    ;;
esac
echo "EDINET の同期が終わりました ($1)"
