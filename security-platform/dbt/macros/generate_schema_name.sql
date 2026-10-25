{#- staging / marts / history をそのままスキーマ名にする (main_staging のような接頭辞を付けない) -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
  {{ custom_schema_name | trim if custom_schema_name else target.schema }}
{%- endmacro %}
