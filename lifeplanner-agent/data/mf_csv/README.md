# MF CSV 配置ディレクトリ

Money Forward ME からエクスポートした **実家計データ CSV** をここに置く。

## 取り扱いルール

- **実データは一切コミットしない**。`.gitignore` により `*.csv` は自動的に追跡対象外になっている
- **追跡対象**は本 README と `.gitkeep` のみ
- 共有・アップロードする場合は事前に匿名化すること

## 置き方

```
data/mf_csv/
├── README.md            (本ファイル・tracked)
├── .gitkeep             (tracked)
└── 収入・支出詳細_2026-04-01_2026-04-30.csv  (ignored)
```

## エンコーディング

- Shift-JIS（CP932）が既定。Python では `encoding="cp932"` で読み込む
- UTF-8 で保存し直した場合も import 側で判定する想定

## 取り込み（想定コマンド）

Phase 1 以降で追加予定:

```bash
# ローカル動作確認用
uv run python -m app.agents.csv_importer --path data/mf_csv/収入・支出詳細_*.csv
```

本番環境では Web UI / LINE Bot からアップロードし、Cloud Storage 経由で処理する。
