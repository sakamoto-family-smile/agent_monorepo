{#-
  Raw 層: Hive パーティション構造の JSONL を union で読むスナップショットテーブル。
  DuckDB の read_json_auto は:
    - hive_partitioning=true で service_name / event_type / dt / hour がカラム化される
    - union_by_name=true で event_type 間のフィールド差異を吸収 (不在は NULL)
  view だと後続クエリ時の cwd に path の解釈が依存するため、table でスナップショット化する。
  path は `raw_root` 変数 (dbt_project 内 var or CLI `--vars`) で上書き可能。
-#}

{{ config(materialized='table') }}
{% set raw_root = var('raw_root', '../data/raw') %}

SELECT *
FROM read_json_auto(
  '{{ raw_root }}/**/*.jsonl*',
  hive_partitioning = true,
  union_by_name = true,
  format = 'newline_delimited',
  ignore_errors = false
)
