# NOTICE — `.claude/` ディレクトリの出典と再現方法

このディレクトリは [ECC (Everything Claude Code)](https://github.com/affaan-m/ECC) の
プロジェクトレベル install (`--target claude-project --profile full`) で生成されたものです。

## ライセンス

- **ECC**: MIT License — `Copyright (c) 2026 Affaan Mustafa`
- 本ディレクトリ内のコンテンツのライセンスは `.claude/LICENSE` を参照

## install 時の情報

| 項目 | 値 |
|---|---|
| ECC version | `2.0.0-rc.1` |
| Profile | `full` |
| Target | `claude-project` |
| Install 日 | 2026-05-28 |
| 取得元 commit | https://github.com/affaan-m/ECC (default branch HEAD time of install) |

## 再現方法 (新規 clone / 別マシン)

```bash
# 1. monorepo を clone
git clone https://github.com/sakamoto-family-smile/agent_monorepo.git
cd agent_monorepo

# 2. ECC を再 install (install-state.json の絶対パスを当該環境に書き換え)
scripts/setup-ecc.sh
```

`scripts/setup-ecc.sh` は ECC リポジトリを `/tmp/ECC-upstream` に clone し、
`install.sh --target claude-project --profile full` で `.claude/` 配下を再生成します。

既に commit 済みのコンテンツに変更があった場合、git diff で確認・必要に応じてマージ。

## アップグレード方法

```bash
scripts/setup-ecc.sh --upgrade
```

ECC の upstream 最新版を取得し、`.claude/` を再生成します。生成後の diff を
PR として上げる運用を推奨。

## 何が含まれて、何が含まれないか

| 含まれる (commit 対象) | 含まれない (gitignore) |
|---|---|
| `agents/` (63 agents) | `ecc/install-state.json` (絶対パス含むため) |
| `skills/ecc/` (249 skills) | Claude Code の per-user runtime state |
| `rules/ecc/` (言語別ルール) | (`sessions/` / `projects/` / `.credentials.json` 等) |
| `commands/` (slash commands) | |
| `hooks/` (`hooks.json` + `memory-persistence/`) | |
| `mcp-configs/mcp-servers.json` | |
| `marketplace.json` / `plugin.json` | |
| `scripts/` (ECC ヘルパー) | |
| トップレベルガイド (`AGENTS.md` 等) | |

## 既存 monorepo との関係

- 既存の `.claude/rules/ecc/` (project instructions として CLAUDE.md 経由で読まれていた)
  と統合 / 上書き
- 既存 `.gitignore` の `.claude/` ルールは whitelist 方式に変更
  (詳細はルート `.gitignore` のコメント参照)

## 注意事項

- Claude Code でこの monorepo を開くと、`.claude/agents/` 配下の 63 agents と
  `.claude/skills/ecc/` 配下の 249 skills が自動的に利用可能になります
- `~/.claude/` (user-level) で別途 ECC を install していると **重複** が発生する可能性。
  ECC docs の "Do not stack install methods" 警告に従って、user-level / project-level の
  どちらか一方に統一することを推奨
- 本 monorepo は **public repo** のため、ECC をここに置く時点で実質再配布となる。
  MIT ライセンスの条件は本ファイルと `LICENSE` の同梱で満たしている
