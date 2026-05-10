"""pdf_pipeline: PDF 構造化 + 差分検知 + 鮮度メタデータ。

ETL Cloud Run Jobs (proposal 0003 §4.5.4) で利用される。

- `hash_diff`: SHA-256 で前回取得との差分を検知 (無駄な処理を避ける)
- `freshness`: FreshnessMetadata を自動付与
- `docling_wrapper`: Docling で PDF を章別 chunk に構造化 (optional dep)
"""

from fujisawa_platform.pdf_pipeline.docling_wrapper import (
    DoclingNotInstalledError,
    PdfChunk,
    extract_chunks,
)
from fujisawa_platform.pdf_pipeline.freshness import (
    build_freshness,
    parse_pdf_date_from_filename,
)
from fujisawa_platform.pdf_pipeline.hash_diff import compute_hash, has_changed

__all__ = [
    "DoclingNotInstalledError",
    "PdfChunk",
    "build_freshness",
    "compute_hash",
    "extract_chunks",
    "has_changed",
    "parse_pdf_date_from_filename",
]
