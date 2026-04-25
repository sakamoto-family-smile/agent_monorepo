{#-
  クロスDB マクロ。DuckDB (ローカル) と BigQuery (GCP) の文法差を吸収する。

  - star_except: SELECT * EXCLUDE/EXCEPT (...) の adapter dispatch
  - quantile_cont: 連続分位 (DuckDB 厳密 / BQ APPROX_QUANTILES 近似)
  - epoch_seconds_diff: タイムスタンプ差 (秒)
  - parse_event_timestamp: ISO 8601 文字列 → TIMESTAMP

  すべて target.type で分岐。サポート外 type は明示的にエラーを出す。
-#}

{% macro star_except(columns) -%}
  {%- if target.type == 'duckdb' -%}
  EXCLUDE ({{ columns | join(', ') }})
  {%- elif target.type == 'bigquery' -%}
  EXCEPT ({{ columns | join(', ') }})
  {%- else -%}
  {{ exceptions.raise_compiler_error("star_except: unsupported target.type=" ~ target.type) }}
  {%- endif -%}
{%- endmacro %}


{% macro quantile_cont(col, p) -%}
  {%- if target.type == 'duckdb' -%}
  QUANTILE_CONT({{ col }}, {{ p }})
  {%- elif target.type == 'bigquery' -%}
  APPROX_QUANTILES({{ col }}, 100)[OFFSET({{ (p * 100) | int }})]
  {%- else -%}
  {{ exceptions.raise_compiler_error("quantile_cont: unsupported target.type=" ~ target.type) }}
  {%- endif -%}
{%- endmacro %}


{% macro epoch_seconds_diff(later, earlier) -%}
  {%- if target.type == 'duckdb' -%}
  EXTRACT(EPOCH FROM ({{ later }} - {{ earlier }}))
  {%- elif target.type == 'bigquery' -%}
  TIMESTAMP_DIFF({{ later }}, {{ earlier }}, MILLISECOND) / 1000.0
  {%- else -%}
  {{ exceptions.raise_compiler_error("epoch_seconds_diff: unsupported target.type=" ~ target.type) }}
  {%- endif -%}
{%- endmacro %}


{% macro parse_event_timestamp(col) -%}
  {%- if target.type == 'duckdb' -%}
  (CAST({{ col }} AS TIMESTAMP) AT TIME ZONE 'UTC')
  {%- elif target.type == 'bigquery' -%}
  TIMESTAMP({{ col }})
  {%- else -%}
  {{ exceptions.raise_compiler_error("parse_event_timestamp: unsupported target.type=" ~ target.type) }}
  {%- endif -%}
{%- endmacro %}


{#-
  date_from_timestamp: TIMESTAMPTZ から DATE を取り出す。
  DuckDB の DATE() は TIMESTAMPTZ を引数に取れる。BQ は DATE(timestamp, timezone) で
  TZ 込みでキャストする (UTC 固定)。
-#}
{% macro date_from_timestamp(col) -%}
  {%- if target.type == 'duckdb' -%}
  DATE({{ col }})
  {%- elif target.type == 'bigquery' -%}
  DATE({{ col }}, 'UTC')
  {%- else -%}
  {{ exceptions.raise_compiler_error("date_from_timestamp: unsupported target.type=" ~ target.type) }}
  {%- endif -%}
{%- endmacro %}
