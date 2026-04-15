"""Uploaded file text extraction utilities."""
import io
from fastapi import UploadFile

# 1 ファイルあたりの最大サイズ (5 MB)
MAX_FILE_SIZE = 5 * 1024 * 1024
# チャンク読み込みサイズ
_CHUNK_SIZE = 64 * 1024  # 64 KB

SUPPORTED_TYPES = {
    ".txt": "テキスト",
    ".md": "Markdown",
    ".csv": "CSV",
    ".docx": "Word文書",
    ".pdf": "PDF",
}

# 許可する MIME タイプ（拡張子と組み合わせて検証）
_ALLOWED_MIME_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/pdf",
    # ブラウザによっては .md を octet-stream で送ることがある
    "application/octet-stream",
}


def _ext(filename: str) -> str:
    return ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""


async def _read_with_size_limit(file: UploadFile) -> bytes:
    """チャンク読み込みでサイズ上限を超えたら即 ValueError を送出する。"""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_FILE_SIZE:
            raise ValueError(
                f"ファイルサイズが上限 (5 MB) を超えています: {file.filename}"
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def extract_text(file: UploadFile) -> str:
    """UploadFile からテキストを抽出して返す。"""
    filename = file.filename or ""
    ext = _ext(filename)

    if ext not in SUPPORTED_TYPES:
        raise ValueError(
            f"非対応のファイル形式です: {ext or '不明'} "
            f"(対応形式: {', '.join(SUPPORTED_TYPES)})"
        )

    # Content-Type 検証（拡張子との不一致を検出）
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type and content_type not in _ALLOWED_MIME_TYPES:
        raise ValueError(
            f"非対応の Content-Type です: {content_type}"
        )

    # サイズ制限付きチャンク読み込み（全バッファより先に超過を検出）
    content = await _read_with_size_limit(file)

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
