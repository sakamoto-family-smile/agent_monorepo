"""DB schema loader / DDL の sanity test。"""

from __future__ import annotations

from fujisawa_platform.db import get_init_schema_sql


class TestInitSchema:
    def test_loads(self) -> None:
        sql = get_init_schema_sql()
        assert isinstance(sql, str)
        assert len(sql) > 1000

    def test_contains_pgvector_extension(self) -> None:
        sql = get_init_schema_sql()
        assert "CREATE EXTENSION IF NOT EXISTS vector" in sql

    def test_contains_all_proposed_tables(self) -> None:
        """proposal 0003 §4.3 + 0005 で言及した全テーブルが含まれる。"""
        sql = get_init_schema_sql()
        for table in (
            "pages",
            "pdf_documents",
            "facilities",
            "vacancy_snapshots",
            "application_snapshots",
            "admission_results",
            "competition_stats",
            "etl_runs",
        ):
            assert f"CREATE TABLE IF NOT EXISTS {table}" in sql, f"missing table: {table}"

    def test_admission_results_has_historical_min_index_columns(self) -> None:
        """proposal 0005 §4.4 の M8 反映 (令和 4 年最低内定指数の格納)。"""
        sql = get_init_schema_sql()
        assert "min_basic_score" in sql
        assert "min_priority" in sql
        assert "min_index_notation" in sql

    def test_competition_stats_has_historical_minimum_index_2022(self) -> None:
        """proposal 0005 のハイブリッドモデル: historical_minimum_index_2022。"""
        sql = get_init_schema_sql()
        assert "historical_minimum_index_2022" in sql
