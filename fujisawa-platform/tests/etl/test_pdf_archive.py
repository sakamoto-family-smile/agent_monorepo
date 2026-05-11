"""PdfArchive Protocol + LocalArchive + NullArchive のテスト。

GcsArchive は別ファイル (`test_gcs_archive.py`) で google-cloud-storage を mock。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from fujisawa_platform.etl.pdf_archive import (
    ArchivePut,
    LocalArchive,
    NullArchive,
    PdfArchive,
    archive_path,
)

_NOW = datetime(2026, 5, 11, 3, 0, tzinfo=UTC)


# ─────────────────────────────────────────────────────────────────────
# archive_path: 決定的なパス生成
# ─────────────────────────────────────────────────────────────────────


class TestArchivePath:
    def test_includes_job_year_round_filename(self) -> None:
        path = archive_path(
            job_name="biyearly_admission_etl",
            url="https://www.city.fujisawa.kanagawa.jp/.../r8_admission_1st.pdf",
            year=2026,
            round="1st",
        )
        # admission/2026/1st/<sha256[:16]>-r8_admission_1st.pdf
        assert path.startswith("biyearly_admission_etl/2026/1st/")
        assert path.endswith("-r8_admission_1st.pdf")
        # SHA-256 先頭 16 桁
        prefix_segment = path.split("/")[-1]
        digest_part = prefix_segment.split("-", 1)[0]
        assert len(digest_part) == 16

    def test_same_url_same_path(self) -> None:
        kwargs = {
            "job_name": "biyearly_admission_etl",
            "url": "https://example.com/a.pdf",
            "year": 2026,
            "round": "1st",
        }
        assert archive_path(**kwargs) == archive_path(**kwargs)

    def test_different_url_different_path(self) -> None:
        a = archive_path(
            job_name="biyearly_admission_etl",
            url="https://example.com/a.pdf",
            year=2026,
            round="1st",
        )
        b = archive_path(
            job_name="biyearly_admission_etl",
            url="https://example.com/b.pdf",
            year=2026,
            round="1st",
        )
        assert a != b

    def test_round_optional(self) -> None:
        path = archive_path(
            job_name="monthly_vacancy_etl",
            url="https://example.com/v.pdf",
            year=2026,
        )
        # round 省略時は year までで止める
        assert path.startswith("monthly_vacancy_etl/2026/")
        assert "1st" not in path
        assert "2nd" not in path

    def test_handles_url_without_extension(self) -> None:
        """URL から filename が取れない場合は .pdf 拡張子を付ける。"""
        path = archive_path(
            job_name="biyearly_admission_etl",
            url="https://example.com/download?id=123",
            year=2026,
            round="1st",
        )
        assert path.endswith(".pdf")

    def test_strips_query_string_from_filename(self) -> None:
        path = archive_path(
            job_name="biyearly_admission_etl",
            url="https://example.com/r8.pdf?ts=12345",
            year=2026,
            round="1st",
        )
        # query string はファイル名には含まれない
        assert "?" not in path
        assert path.endswith("-r8.pdf")

    def test_invalid_chars_sanitized(self) -> None:
        """ファイル名に含めない方が安全な文字 (空白等) は - に置換。"""
        path = archive_path(
            job_name="biyearly_admission_etl",
            url="https://example.com/foo bar.pdf",
            year=2026,
            round="1st",
        )
        assert " " not in path
        assert path.endswith("-foo-bar.pdf")


# ─────────────────────────────────────────────────────────────────────
# LocalArchive
# ─────────────────────────────────────────────────────────────────────


class TestLocalArchive:
    @pytest.mark.asyncio
    async def test_put_creates_file(self, tmp_path: Path) -> None:
        archive: PdfArchive = LocalArchive(root=tmp_path)

        result = await archive.put(
            path="biyearly_admission_etl/2026/1st/abc-x.pdf",
            content=b"%PDF-fake",
            source_url="https://example.com/x.pdf",
            fetched_at=_NOW,
        )
        assert isinstance(result, ArchivePut)
        assert result.backend == "local"
        assert result.path == "biyearly_admission_etl/2026/1st/abc-x.pdf"

        target = tmp_path / "biyearly_admission_etl/2026/1st/abc-x.pdf"
        assert target.read_bytes() == b"%PDF-fake"

    @pytest.mark.asyncio
    async def test_put_overwrites_existing(self, tmp_path: Path) -> None:
        archive = LocalArchive(root=tmp_path)
        path = "biyearly_admission_etl/2026/1st/dup.pdf"

        await archive.put(
            path=path, content=b"old", source_url="https://example.com/x.pdf", fetched_at=_NOW
        )
        await archive.put(
            path=path, content=b"new", source_url="https://example.com/x.pdf", fetched_at=_NOW
        )

        target = tmp_path / path
        assert target.read_bytes() == b"new"

    @pytest.mark.asyncio
    async def test_exists_returns_true_after_put(self, tmp_path: Path) -> None:
        archive = LocalArchive(root=tmp_path)
        await archive.put(
            path="x.pdf", content=b"x", source_url="https://example.com/x.pdf", fetched_at=_NOW
        )
        assert await archive.exists("x.pdf") is True

    @pytest.mark.asyncio
    async def test_exists_returns_false_when_missing(self, tmp_path: Path) -> None:
        archive = LocalArchive(root=tmp_path)
        assert await archive.exists("never-created.pdf") is False

    @pytest.mark.asyncio
    async def test_get_returns_bytes(self, tmp_path: Path) -> None:
        archive = LocalArchive(root=tmp_path)
        await archive.put(
            path="x.pdf", content=b"hello", source_url="https://example.com/x.pdf", fetched_at=_NOW
        )
        assert await archive.get("x.pdf") == b"hello"

    @pytest.mark.asyncio
    async def test_get_raises_on_missing(self, tmp_path: Path) -> None:
        archive = LocalArchive(root=tmp_path)
        with pytest.raises(FileNotFoundError):
            await archive.get("missing.pdf")

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, tmp_path: Path) -> None:
        """`../etc/passwd` のようなパスを put しても root の外には書かない。"""
        archive = LocalArchive(root=tmp_path)
        with pytest.raises(ValueError, match="path traversal"):
            await archive.put(
                path="../escape.pdf",
                content=b"x",
                source_url="https://example.com/x.pdf",
                fetched_at=_NOW,
            )


# ─────────────────────────────────────────────────────────────────────
# NullArchive
# ─────────────────────────────────────────────────────────────────────


class TestNullArchive:
    @pytest.mark.asyncio
    async def test_put_returns_skipped_status(self) -> None:
        archive: PdfArchive = NullArchive()
        result = await archive.put(
            path="x.pdf", content=b"x", source_url="https://example.com/x.pdf", fetched_at=_NOW
        )
        assert result.backend == "null"
        assert result.path == "x.pdf"

    @pytest.mark.asyncio
    async def test_exists_always_false(self) -> None:
        archive = NullArchive()
        assert await archive.exists("anything") is False

    @pytest.mark.asyncio
    async def test_get_raises(self) -> None:
        """NullArchive はバイトを保持しない → get は NotImplementedError。"""
        archive = NullArchive()
        with pytest.raises(FileNotFoundError):
            await archive.get("x")


# ─────────────────────────────────────────────────────────────────────
# Protocol 互換性
# ─────────────────────────────────────────────────────────────────────


def test_local_archive_satisfies_protocol() -> None:
    """`LocalArchive` / `NullArchive` が `PdfArchive` Protocol に従う。"""
    archive_local: PdfArchive = LocalArchive(root=Path("/tmp/x"))  # noqa: S108
    archive_null: PdfArchive = NullArchive()
    assert isinstance(archive_local, PdfArchive)
    assert isinstance(archive_null, PdfArchive)


# ─────────────────────────────────────────────────────────────────────
# build_archive_from_config
# ─────────────────────────────────────────────────────────────────────


class TestBuildArchiveFromConfig:
    def test_null_backend(self) -> None:
        from fujisawa_platform.etl.pdf_archive import NullArchive, build_archive_from_config

        archive = build_archive_from_config(backend="null")
        assert isinstance(archive, NullArchive)

    def test_local_backend_requires_root(self) -> None:
        from fujisawa_platform.etl.pdf_archive import build_archive_from_config

        with pytest.raises(ValueError, match="local_root"):
            build_archive_from_config(backend="local")

    def test_local_backend_with_root(self, tmp_path: Path) -> None:
        from fujisawa_platform.etl.pdf_archive import LocalArchive, build_archive_from_config

        archive = build_archive_from_config(backend="local", local_root=tmp_path)
        assert isinstance(archive, LocalArchive)

    def test_gcs_backend_requires_bucket(self) -> None:
        from fujisawa_platform.etl.pdf_archive import build_archive_from_config

        with pytest.raises(ValueError, match="bucket"):
            build_archive_from_config(backend="gcs")

    def test_gcs_backend_with_bucket(self) -> None:
        from fujisawa_platform.etl.pdf_archive import GcsArchive, build_archive_from_config

        archive = build_archive_from_config(backend="gcs", bucket="fujisawa-pdf-archive")
        assert isinstance(archive, GcsArchive)

    def test_unknown_backend_rejected(self) -> None:
        from fujisawa_platform.etl.pdf_archive import build_archive_from_config

        with pytest.raises(ValueError, match="unknown pdf_archive_backend"):
            build_archive_from_config(backend="s3")
