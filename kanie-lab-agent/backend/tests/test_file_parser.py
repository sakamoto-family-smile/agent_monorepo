"""Unit tests for file_parser service."""
import io
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import UploadFile

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.file_parser import extract_text, build_file_context, MAX_FILE_SIZE, SUPPORTED_TYPES


def make_upload_file(filename: str, content: bytes) -> UploadFile:
    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = filename
    mock_file.read = AsyncMock(return_value=content)
    return mock_file


@pytest.mark.anyio
async def test_extract_txt():
    f = make_upload_file("sample.txt", b"Hello World")
    result = await extract_text(f)
    assert result == "Hello World"


@pytest.mark.anyio
async def test_extract_md():
    f = make_upload_file("notes.md", b"# Title\n\nBody text")
    result = await extract_text(f)
    assert "Title" in result


@pytest.mark.anyio
async def test_extract_csv():
    f = make_upload_file("data.csv", b"col1,col2\nval1,val2")
    result = await extract_text(f)
    assert "col1" in result


@pytest.mark.anyio
async def test_unsupported_extension():
    f = make_upload_file("file.xyz", b"data")
    with pytest.raises(ValueError, match="非対応のファイル形式"):
        await extract_text(f)


@pytest.mark.anyio
async def test_file_too_large():
    large_content = b"x" * (MAX_FILE_SIZE + 1)
    f = make_upload_file("big.txt", large_content)
    with pytest.raises(ValueError, match="5 MB"):
        await extract_text(f)


@pytest.mark.anyio
async def test_no_extension():
    f = make_upload_file("noext", b"data")
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
