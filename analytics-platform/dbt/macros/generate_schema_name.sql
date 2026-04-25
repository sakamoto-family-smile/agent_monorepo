{#-
  schema 命名規則の adapter 別オーバライド。

  - DuckDB: dbt 既定 (`{target.schema}_{custom}`) を維持。`main_raw` / `main_staging` / `main_marts`。
  - BigQuery: `analytics_{custom}` で固定し、`analytics_raw` / `analytics_staging` / `analytics_marts`
              にデータセットを分離。target.dataset は `generate_database_name` 的な役割で
              使うが、ここでは無視して dataset を `analytics_{custom}` に統一する。
-#}

{% macro generate_schema_name(custom_schema_name, node) -%}
  {%- set default_schema = target.schema -%}
  {%- if custom_schema_name is none -%}
    {{ default_schema }}
  {%- elif target.type == 'bigquery' -%}
    analytics_{{ custom_schema_name | trim }}
  {%- else -%}
    {{ default_schema }}_{{ custom_schema_name | trim }}
  {%- endif -%}
{%- endmacro %}
