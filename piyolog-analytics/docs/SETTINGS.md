# 子情報の設定 (Phase 4-B)

ぴよログ分析 Bot は子の生年月日 / 名前を使って LLM 相談時の「月齢」表示や
プロンプト中の名前置換を行う。Phase 4-B から DB ベースで管理できるように
した。

## エンドユーザ操作 (LINE)

### ⚙️ 設定 ボタン → Quick Reply

リッチメニュー右下の `⚙️ 設定` を押すと、Quick Reply で 3 ボタンが出る:

| ボタン | 動作 |
|---|---|
| 📅 子の生年月日 | LINE 標準 datetime picker (mode=date) で日付選択 |
| ✏️ 子の名前 | 「名前: たろう」のテキスト入力を促すメッセージを返す |
| キャンセル | 設定 UI を閉じる |

### 生年月日: datetime picker

- LINE iOS / Android のドラムロール UI で日付を選択
- 選択した日付は postback `action=child_set_birth_date` + `params.date=YYYY-MM-DD`
  として届き、`children` table に upsert
- 既登録の値があれば picker の `initial` にその値が入る

### 名前: テキスト入力

- LINE は Quick Reply にフリーテキスト入力 UI を持たないため、Bot 側で
  「`名前: たろう` のように送ってください」とプロンプトする
- 受け取り側は `_handle_text` で `名前:` / `名前：` / `名前 ` / `name:` /
  `name ` の prefix を検出して `children.name` に保存
- バリデーション: 1〜32 文字、改行 / タブ不可
- 「名前: キャンセル」で設定終了 (DB は更新しない)

## context_builder のソース

`build_recent_context()` は子の生年月日 / 名前を `children` テーブル
(= ChildRepo) から `(family_id, child_id)` で取得する。

未登録なら「月齢: 不明 (⚙️ 設定 から子の生年月日を登録してください)」と
出る (LLM はこの旨を読み取って、ユーザに登録を促す挙動になる)。

env (`CHILD_BIRTH_DATE`) は廃止 (`children` テーブルに一本化)。
テストから直接注入したい場合のみ `birth_date` / `child_name` 引数で
override 可能 (本番では使わない)。

## DB スキーマ (alembic 0003_children)

```
children
  family_id   TEXT  PK
  child_id    TEXT  PK    (default: "default" — Phase 1 から固定)
  birth_date  TEXT  NULL  (YYYY-MM-DD)
  name        TEXT  NULL
  updated_at  TEXT  NOT NULL
```

`piyolog_events.child_id` と整合する想定。複数子対応は将来の拡張で
`child_id` を per-child に分岐させる際に使う (現状は `default` 固定)。

## バックアップとの関係

`children` も `make backup` の対象。`pg_dump` ベースの `gcloud sql export sql`
は全テーブルを dump するため、Phase 4-A の手順 (`make backup` →
`make tf-destroy` → `make tf-apply` → `make restore`) で復元される。
