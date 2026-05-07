# Documentation Templates & Index

このディレクトリには、モノレポ全体で共通に使うドキュメントテンプレートと、
クロスエージェントなドキュメントを配置する。

## テンプレート一覧

| ファイル | 用途 | 配置先 |
|---|---|---|
| [`PROPOSALS/TEMPLATE.md`](PROPOSALS/TEMPLATE.md) | per-feature 提案 / ADR (KEP ベース) | `docs/PROPOSALS/NNNN-...md` (本ディレクトリ配下) |
| [`SYSTEM_DESIGN_TEMPLATE.md`](SYSTEM_DESIGN_TEMPLATE.md) | per-system 設計書 (1 エージェント全体) | `<agent>/docs/DESIGN.md` (各エージェント配下) |
| [`README_TEMPLATE.md`](README_TEMPLATE.md) | エージェント README (Quickstart 主体) | `<agent>/README.md` (各エージェント配下) |

将来追加予定:
- `OPERATIONS_TEMPLATE.md` — deploy / backup / restore 等の運用手順テンプレ

## 凡例

各テンプレ内のセクション見出しは以下のマーカーで重要度を示す:

| マーカー | 意味 |
|---|---|
| `[必須]` | 空にしない (書くことがなければ "N/A" と理由を記載) |
| `[推奨]` | 該当する場合のみ書く (不要なら節ごと削除可) |
| `[不要]` | 削除して構わない (規模に対して過剰、参考のみ残置) |

メモ帳 / vim / terminal すべてで確実に読めるよう、絵文字 (🟢🟡🔴) ではなく
角括弧テキストを採用。`grep '\[必須\]' docs/...` でフィルタ可能。

## 3 つのテンプレの使い分け

```
                  ┌─ per-feature 提案 (PROPOSALS/TEMPLATE.md)
                  │   └ 1 機能 = 1 ファイル、ADR を兼ねる、複数 PR に対応
                  │
モノレポ ─┬───────┤
          │       │
          │       ├─ per-system 設計書 (SYSTEM_DESIGN_TEMPLATE.md)
          │       │   └ 1 エージェント = 1 ファイル、機能要件 / NFR /
          │       │     アーキテクチャ / Roadmap / 設計判断ログ
          │       │
          │       └─ README (README_TEMPLATE.md)
          │           └ Quickstart + 主要 API + 環境変数 + 関連 doc へのリンク
          │
          └─ docs/PROPOSALS/ (本ディレクトリ配下、モノレポ共通)
```

### どれを書くべきか

| やりたいこと | 使うテンプレ |
|---|---|
| 新エージェントを立ち上げる | `README_TEMPLATE.md` + `SYSTEM_DESIGN_TEMPLATE.md` |
| 既存エージェントに大きな機能を追加 (複数 PR) | `PROPOSALS/TEMPLATE.md` で 1 件作成 → 該当エージェントの DESIGN.md の機能要件表に追記 |
| アーキテクチャを見直す (DB schema 大改修等) | `PROPOSALS/TEMPLATE.md` + DESIGN.md の更新 |
| 軽微なバグ修正 | テンプレ不要、commit message + PR description で十分 |
| 運用手順を整備 (deploy 手順書) | (将来) `OPERATIONS_TEMPLATE.md`、現状は ad-hoc に書いて OK |

## ドキュメント移行計画

既存ドキュメントを段階的に新テンプレ準拠に寄せる。詳細は [`MIGRATION_PLAN.md`](MIGRATION_PLAN.md) 参照。

ハイレベル:
1. **Stage 1**: テンプレ整備 (本 PR で完了予定)
2. **Stage 2**: 主要 3 エージェント (lifeplanner / piyolog / driving-license-bot) を移行
3. **Stage 3**: 残エージェント + Operations runbook テンプレ + 全 README 統一

既存の README / design.md / SETTINGS.md などは段階移行までそのまま運用 OK。
新規分から本テンプレを使う方針 (沈没コストを払わない)。

## モノレポ全体のクロスドキュメント

(該当するものがあればここに追加)

- [`PROPOSALS/`](PROPOSALS/) — モノレポ共通の機能提案ライブラリ
