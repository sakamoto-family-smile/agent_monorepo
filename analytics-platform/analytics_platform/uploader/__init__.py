"""ローカル疑似アップローダ。

`data/raw/` から `data/uploaded/` へ移動する。失敗時は `data/dead_letter/` へ。
GCP 移行時はここを GCS Uploader に差し替える (設計書 §9.3.2)。
"""

from .local_uploader import LocalUploader, UploadOutcome

__all__ = ["LocalUploader", "UploadOutcome"]
