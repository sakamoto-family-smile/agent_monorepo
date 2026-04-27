"""agent モジュール共通の例外。"""

from __future__ import annotations


class LLMClientError(Exception):
    """LLM 呼び出し（Vertex AI 等）の汎用エラー。"""


class GenerationParseError(Exception):
    """LLM 出力の JSON パースに失敗した。

    LLM がスキーマ違反を返したことを示す。retry の判断材料になるよう、
    元の生レスポンスを `raw` に保持する。
    """

    def __init__(self, message: str, *, raw: str = "") -> None:
        super().__init__(message)
        self.raw = raw


class GenerationValidationError(Exception):
    """LLM 出力は JSON だが、Question スキーマに違反した。

    pydantic の ValidationError をラップする。`details` に元エラー文字列。
    """

    def __init__(self, message: str, *, details: str = "") -> None:
        super().__init__(message)
        self.details = details
