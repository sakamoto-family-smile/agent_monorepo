"""抽出パイプライン。出力は ExtractionResult[] (採否は判断しない)。"""

from __future__ import annotations

from .base import Extractor
from .mock_extractor import ErrorMode, InjectionConfig, MockExtractor

__all__ = ["Extractor", "ErrorMode", "InjectionConfig", "MockExtractor"]
