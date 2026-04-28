#!/usr/bin/env bash
# .env.secrets から値を読み、Secret Manager に投入する。
#
# 利点:
# - 毎回トークンを手で貼り付けなくて済む
# - 末尾改行が混入しない（printf '%s' で投入）
# - シェル特殊文字を正しく escape
# - secret 枠が無ければ枠だけ作って投入を促す
#
# 使い方:
#   .env.secrets を埋めて
#   make secrets-push
#
# あるいは別ファイルから:
#   ENV_FILE=path/to/secrets.env make secrets-push

set -euo pipefail

ENV_FILE="${ENV_FILE:-.env.secrets}"
PROJECT="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"

if [[ -z "${PROJECT}" ]]; then
    echo "ERROR: GOOGLE_CLOUD_PROJECT が解決できません。" >&2
    echo "  gcloud config set project <PROJECT_ID> または env で指定" >&2
    exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
    echo "ERROR: ${ENV_FILE} が見つかりません。" >&2
    echo "  cp .env.secrets.example ${ENV_FILE} で作成して値を埋めてください。" >&2
    exit 1
fi

echo "[push_line_secrets] project=${PROJECT}"
echo "[push_line_secrets] reading ${ENV_FILE}"

# .env を sourcing（LINE token は base64 で shell 特殊文字を含まない）
# set -a でこの関数内の declare を export 扱いにし、孫プロセスで使える状態にする
set -a
# shellcheck source=/dev/null
source "${ENV_FILE}"
set +a

# secret name と env キーの対応
declare -A SECRET_MAP=(
    [driving-license-bot-line-channel-secret]="LINE_CHANNEL_SECRET"
    [driving-license-bot-line-channel-access-token]="LINE_CHANNEL_ACCESS_TOKEN"
    [driving-license-bot-operator-line-user-ids]="OPERATOR_LINE_USER_IDS"
    [driving-license-bot-line-login-channel-secret]="LINE_LOGIN_CHANNEL_SECRET"
)

# 必須キー
REQUIRED_ENVS=(LINE_CHANNEL_SECRET LINE_CHANNEL_ACCESS_TOKEN)

# 必須キー欠落チェック
for k in "${REQUIRED_ENVS[@]}"; do
    if [[ -z "${!k:-}" ]]; then
        echo "ERROR: ${k} が ${ENV_FILE} に未設定です。" >&2
        exit 1
    fi
done

# secret 枠が無いものを検出 → tf-apply 案内
MISSING_SECRETS=()
for secret in "${!SECRET_MAP[@]}"; do
    env_key="${SECRET_MAP[$secret]}"
    val="${!env_key:-}"
    [[ -z "${val}" ]] && continue   # 任意キーで値が空なら skip
    if ! gcloud secrets describe "${secret}" --project="${PROJECT}" >/dev/null 2>&1; then
        MISSING_SECRETS+=("${secret}")
    fi
done

if (( ${#MISSING_SECRETS[@]} > 0 )); then
    echo "ERROR: 以下の Secret Manager 枠が存在しません:" >&2
    for s in "${MISSING_SECRETS[@]}"; do echo "  - ${s}" >&2; done
    echo "" >&2
    echo "  対応: 'make tf-apply' で枠を作ってから本コマンドを再実行してください。" >&2
    exit 1
fi

# 値投入
push_one() {
    local secret="$1"
    local value="$2"
    # printf '%s' で末尾改行が付かない形で stdin に流す
    printf '%s' "${value}" | gcloud secrets versions add "${secret}" \
        --project="${PROJECT}" --data-file=- >/dev/null
    local len
    len=$(printf '%s' "${value}" | wc -c | tr -d ' ')
    echo "  ✓ ${secret}  (${len} bytes)"
}

echo "[push_line_secrets] pushing values ..."
for secret in "${!SECRET_MAP[@]}"; do
    env_key="${SECRET_MAP[$secret]}"
    val="${!env_key:-}"
    if [[ -z "${val}" ]]; then
        echo "  - ${secret}  (skipped: ${env_key} is empty)"
        continue
    fi
    push_one "${secret}" "${val}"
done

echo "[push_line_secrets] done."
echo ""
echo "確認:"
echo "  gcloud secrets versions list driving-license-bot-line-channel-access-token \\"
echo "    --project=${PROJECT}"
