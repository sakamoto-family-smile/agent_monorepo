"""Uploaded file text extraction utilities."""
import io
from fastapi import UploadFile

# 1 ファイルあたりの最大サイズ (5 MB)
MAX_FILE_SIZE = 5 * 1024 * 1024

SUPPORTED_TYPES = {
    ".txt": "テキスト",
    ".md": "Markdown",
    ".csv": "CSV",
    ".docx": "Word文書",
    ".pdf": "PDF",
}


def _ext(filename: str) -> str:
    return ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""


async def extract_text(file: UploadFile) -> str:
    """UploadFile からテキストを抽出して返す。"""
    filename = file.filename or ""
    ext = _ext(filename)

    if ext not in SUPPORTED_TYPES:
        raise ValueError(
            f"非対応のファイル形式です: {ext or '不明'} "
            f"(対応形式: {', '.join(SUPPORTED_TYPES)})"
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise ValueError(
            f"ファイルサイズが上限 (5 MB) を超えています: {filename}"
        )

    if ext in (".txt", ".md", ".csv"):
        return content.decode("utf-8", errors="replace")

    if ext == ".docx":
        from docx import Document  # python-docx
        doc = Document(io.BytesIO(content))
        lines = [para.text for para in doc.paragraphs if para.text.strip()]
        return "\n".join(lines)

    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(p for p in pages if p.strip())

    raise ValueError(f"非対応の形式: {ext}")


def build_file_context(filename: str, text: str) -> str:
    """抽出テキストをプロンプトに埋め込む形式にフォーマットする。"""
    return (
        f"\n\n---\n"
        f"【添付ファイル: {filename}】\n\n"
        f"{text}\n"
        f"---"
    )
