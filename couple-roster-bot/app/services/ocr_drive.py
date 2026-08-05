"""Google Drive OCR エンジン（無料枠で使える文字認識）。

画像を Drive に「Google ドキュメントへ変換」してアップロードすると OCR が走る。
その本文テキストを取り出し、一時ファイルは即削除する（画像を残さない方針）。

依存 (`google-api-python-client`) は `ocr-drive` extra。実行時のみ import する。
"""

from __future__ import annotations

import io

_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]


class DriveOcrEngine:
    """Drive API v3 経由の OCR。認証は ADC（Cloud Run のサービスアカウント等）。"""

    def __init__(self, ocr_language: str = "ja") -> None:
        self._ocr_language = ocr_language

    def recognize(self, image_bytes: bytes) -> str:
        import google.auth
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseUpload

        creds, _ = google.auth.default(scopes=_DRIVE_SCOPES)
        service = build("drive", "v3", credentials=creds, cache_discovery=False)

        media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype="image/png", resumable=False)
        file_metadata = {
            "name": "roster-ocr-temp",
            "mimeType": "application/vnd.google-apps.document",
        }
        created = (
            service.files()
            .create(
                body=file_metadata,
                media_body=media,
                ocrLanguage=self._ocr_language,
                fields="id",
            )
            .execute()
        )
        file_id = created["id"]
        try:
            exported = (
                service.files()
                .export(fileId=file_id, mimeType="text/plain")
                .execute()
            )
            if isinstance(exported, bytes):
                return exported.decode("utf-8", errors="replace")
            return str(exported)
        finally:
            # 個人情報を残さないため、OCR 用の一時ドキュメントは必ず削除する。
            service.files().delete(fileId=file_id).execute()


__all__ = ["DriveOcrEngine"]
