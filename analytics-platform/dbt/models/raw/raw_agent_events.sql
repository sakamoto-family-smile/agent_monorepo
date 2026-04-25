{#-
  Raw 層: Hive パーティション構造の JSONL を 1 つのテーブルとして取り回す。

  - DuckDB (local): `read_json_auto` で `data/uploaded/**/*.jsonl*` を直読み。
      hive_partitioning=true で service_name / event_type / dt / hour がカラム化される。
      view だと後続クエリ時の cwd に path 解釈が依存するため、table でスナップショット化する。
  - BigQuery (gcp): 事前作成した external table (`source('analytics_raw_external','agent_events_external')`)
      を参照。view で OK (BQ external は cwd 依存しない)。
-#}

{% if target.type == 'duckdb' %}
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

{% elif target.type == 'bigquery' %}
  {{ config(materialized='view') }}

  SELECT *
  FROM {{ source('analytics_raw_external', 'agent_events_external') }}

{% else %}
  {{ exceptions.raise_compiler_error("raw_agent_events: unsupported target.type=" ~ target.type) }}
{% endif %}
