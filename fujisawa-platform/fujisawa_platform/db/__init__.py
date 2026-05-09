"""DB 初期化スキーマと SQL helpers。

`init_schema.sql` は `fujisawa_kb_db` (proposal 0003 §4.3) の DDL。
ETL Job が初回実行前に `psql -f init_schema.sql` で適用する。
"""

from __future__ import annotations

from importlib.resources import files

_PACKAGE = "fujisawa_platform.db"


def get_init_schema_sql() -> str:
    """`init_schema.sql` を文字列として返す。"""
    return files(_PACKAGE).joinpath("init_schema.sql").read_text(encoding="utf-8")


__all__ = ["get_init_schema_sql"]
