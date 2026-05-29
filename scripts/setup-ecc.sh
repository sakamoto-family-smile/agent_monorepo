#!/usr/bin/env bash
# setup-ecc.sh — agent_monorepo の .claude/ を ECC で再生成する
#
# 用途:
#   - 新規 clone 後の初回 setup (install-state.json を環境に合わせて再生成)
#   - ECC upstream のアップグレード適用
#
# 使い方:
#   scripts/setup-ecc.sh                    # 既定: default branch HEAD
#   scripts/setup-ecc.sh --upgrade          # upstream 最新を pull して再 install
#   scripts/setup-ecc.sh --profile minimal  # profile を上書き (既定: full)
#   scripts/setup-ecc.sh --dry-run          # 実 install せず計画だけ表示
#
# 前提:
#   - git, node (>=18), npm が利用可能であること
#   - monorepo のルートで実行すること
#
# 詳細: .claude/NOTICE.md

set -euo pipefail

PROFILE="full"
UPGRADE=0
DRY_RUN=0
ECC_REPO="https://github.com/affaan-m/ECC.git"
ECC_DIR="${ECC_DIR:-/tmp/ECC-upstream}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --upgrade) UPGRADE=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --ecc-dir) ECC_DIR="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

# monorepo ルートで実行されているか確認
if [[ ! -f "pyproject.toml" && ! -f "README.md" ]] || [[ ! -d "docs/PROPOSALS" ]]; then
  echo "[setup-ecc] ERROR: monorepo ルート (agent_monorepo) で実行してください" >&2
  exit 1
fi
REPO_ROOT="$(pwd)"

# ECC repo を clone or update
if [[ -d "$ECC_DIR/.git" ]]; then
  if [[ $UPGRADE -eq 1 ]]; then
    echo "[setup-ecc] upgrading ECC at $ECC_DIR ..."
    git -C "$ECC_DIR" fetch --depth=1 origin
    git -C "$ECC_DIR" reset --hard origin/HEAD
  else
    echo "[setup-ecc] reusing existing ECC at $ECC_DIR (use --upgrade to refresh)"
  fi
else
  echo "[setup-ecc] cloning ECC into $ECC_DIR ..."
  git clone --depth=1 "$ECC_REPO" "$ECC_DIR"
fi

# install 実行
INSTALL_ARGS=(--target claude-project --profile "$PROFILE")
[[ $DRY_RUN -eq 1 ]] && INSTALL_ARGS+=(--dry-run)

echo "[setup-ecc] running: $ECC_DIR/install.sh ${INSTALL_ARGS[*]}"
( cd "$REPO_ROOT" && "$ECC_DIR/install.sh" "${INSTALL_ARGS[@]}" )

if [[ $DRY_RUN -eq 1 ]]; then
  echo "[setup-ecc] dry-run 完了。実 install するには --dry-run を外して再実行"
  exit 0
fi

# install-state.json は環境固有の絶対パスを含むため commit 対象外
# (.gitignore で除外済み、念のため確認)
if [[ -f .claude/ecc/install-state.json ]]; then
  if git check-ignore -q .claude/ecc/install-state.json 2>/dev/null; then
    echo "[setup-ecc] OK: install-state.json is gitignored"
  else
    echo "[setup-ecc] WARN: install-state.json は .gitignore で除外すべきです" >&2
  fi
fi

echo ""
echo "[setup-ecc] 完了。git status で差分を確認してください:"
echo "  - 新規 install: ファイル追加が大量に出ます (初回想定)"
echo "  - upgrade: 差分のみ"
echo ""
echo "[setup-ecc] 詳細は .claude/NOTICE.md 参照"
