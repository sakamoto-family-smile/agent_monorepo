"""JSONL シンク実装。"""

from .file_sink import JsonlSink, RotatingFileSink

__all__ = ["JsonlSink", "RotatingFileSink"]
