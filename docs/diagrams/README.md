# GCP Architecture Diagram (JSX)

JSX/SVG で記述する GCP 構成図のデモ。追加ランタイム依存なしで React / Next.js にそのまま組み込めます。

## ファイル

| ファイル | 役割 |
|---|---|
| `GcpArchitecture.tsx` | 構成図本体（React コンポーネント）。`NODES` / `EDGES` を編集すれば図が変わる |
| `gcpIconDefs.ts` | **自動生成**。公式 GCP アイコンを衝突しない `<symbol>` スプライトとして埋め込む文字列 |
| `gcp-icon-defs.partial.svg` | **自動生成**。同じスプライト（プレビュー用） |
| `build-icons.mjs` | `gcp-icons-src/` の公式 SVG からスプライトを生成するスクリプト |
| `gcp-icons-src/` | 公式 Google Cloud プロダクトアイコン（再生成用ソース） |
| `render-preview.mjs` | コンポーネントと同じ図を静的 SVG に書き出す（ブラウザ不要の確認用） |
| `gcp-architecture.svg` / `.png` | 生成済みプレビュー |

## 使い方

```tsx
import GcpArchitecture from "@/docs/diagrams/GcpArchitecture";

export default function Page() {
  return <GcpArchitecture />;
}
```

## アイコンの再生成

ソース（`gcp-icons-src/`）を追加・変更したら:

```bash
node docs/diagrams/build-icons.mjs    # gcpIconDefs.ts / *.partial.svg を再生成
node docs/diagrams/render-preview.mjs # 静的プレビューを再生成
```

公式アイコンは内部 CSS クラス（`.cls-*`）や共通 id（`mask` など）を使うため、
`build-icons.mjs` が fill をインライン化し、id を除去して 1 ドキュメント内で
衝突しない `<symbol id="gcp-...">` に変換しています。

## アイコンの出典

Google Cloud 公式アーキテクチャアイコン（<https://cloud.google.com/icons>）。
ブランド/アイコンの利用は Google のガイドラインに従ってください。
