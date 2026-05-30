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

## システム別構成図（`systems/`）

各エージェントシステムのローカル版 / GCP版 構成図を `systems/<name>/` に置きます。
モノレポ全体を俯瞰する GCP 全体構成図は [`systems/_overview/`](./systems/_overview/README.md)。
1 つの **spec ファイル（データ）** から、静的 SVG・PNG・React コンポーネントを生成します。

```text
systems/driving-license-bot/
├── spec.local.mjs                 # データ: ローカル開発構成
├── spec.gcp.mjs                   # データ: GCP 本番構成
├── local.svg / local.png          # 生成物
├── gcp.svg   / gcp.png            # 生成物
├── DrivingLicenseBotDiagram.tsx   # 生成物（埋め込みSVG・依存ゼロ）
└── README.md
```

共有エンジン（`lib/`）:

| ファイル | 役割 |
|---|---|
| `lib/render.mjs` | spec（`nodes`/`edges`/`groups`）→ SVG 文字列のデータ駆動レンダラ |
| `lib/icons.mjs` | 公式 GCP スプライト + 追加アイコン（`extra-icons-src.svg`）を結合 |
| `extra-icons-src.svg` | 非 GCP / ローカル用アイコン（Docker, Postgres, LINE, ngrok 等、`x-*`） |
| `build-system.mjs` | `systems/<dir>` の spec を SVG + TSX に変換 |
| `rasterize.py` | SVG → PNG（PNG出力時のみ CJK フォントに差し替え） |

### 新しいシステムを追加

```bash
cd docs/diagrams
mkdir -p systems/<name>
# spec.local.mjs / spec.gcp.mjs を作成（既存を参考に）
node build-system.mjs systems/<name>
python3 rasterize.py systems/<name>/local.svg systems/<name>/gcp.svg
```

アイコン id は GCP 公式が `gcp-*`、追加分が `x-*`。spec の `icon` にこの id を指定します。

## アイコンの出典

Google Cloud 公式アーキテクチャアイコン（<https://cloud.google.com/icons>）。
ブランド/アイコンの利用は Google のガイドラインに従ってください。
ローカル用の `x-*` アイコンは本リポジトリで作成した簡易フラットアイコンです。
