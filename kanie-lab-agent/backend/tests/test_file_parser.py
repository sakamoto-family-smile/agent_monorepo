"""Unit tests for file_parser service."""
import io
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import UploadFile

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.file_parser import extract_text, build_file_context, MAX_FILE_SIZE, SUPPORTED_TYPES


def make_upload_file(filename: str, content: bytes, content_type: str = "") -> UploadFile:
    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = filename
    mock_file.content_type = content_type
    # チャンク読み込み対応: 最初の呼び出しでコンテンツ、以降は b""
    read_calls = [content, b""]
    mock_file.read = AsyncMock(side_effect=read_calls + [b""] * 100)
    return mock_file


@pytest.mark.anyio
async def test_extract_txt():
    f = make_upload_file("sample.txt", b"Hello World", "text/plain")
    result = await extract_text(f)
    assert result == "Hello World"


@pytest.mark.anyio
async def test_extract_md():
    f = make_upload_file("notes.md", b"# Title\n\nBody text", "text/markdown")
    result = await extract_text(f)
    assert "Title" in result


@pytest.mark.anyio
async def test_extract_csv():
    f = make_upload_file("data.csv", b"col1,col2\nval1,val2", "text/csv")
    result = await extract_text(f)
    assert "col1" in result


@pytest.mark.anyio
async def test_unsupported_extension():
    f = make_upload_file("file.xyz", b"data", "application/octet-stream")
    with pytest.raises(ValueError, match="非対応のファイル形式"):
        await extract_text(f)


@pytest.mark.anyio
async def test_file_too_large():
    # チャンクが MAX_FILE_SIZE+1 バイトを超えた時点で ValueError が発生する
    chunk = b"x" * (MAX_FILE_SIZE + 1)
    f = make_upload_file("big.txt", chunk, "text/plain")
    with pytest.raises(ValueError, match="5 MB"):
        await extract_text(f)


@pytest.mark.anyio
async def test_no_extension():
    f = make_upload_file("noext", b"data", "")
    with pytest.raises(ValueError, match="非対応のファイル形式"):
        await extract_text(f)


def test_build_file_context():
    result = build_file_context("report.txt", "本文テキスト")
    assert "report.txt" in result
    assert "本文テキスト" in result
    assert "添付ファイル" in result


def test_supported_types_coverage():
    assert ".txt" in SUPPORTED_TYPES
    assert ".md" in SUPPORTED_TYPES
    assert ".csv" in SUPPORTED_TYPES
    assert ".docx" in SUPPORTED_TYPES
    assert ".pdf" in SUPPORTED_TYPES
