"""Cloud Vision OCR エンジン（高精度・少額課金）。

日本語の文書テキスト検出に強い。依存 (`google-cloud-vision`) は `ocr-vision`
extra。実行時のみ import する。
"""

from __future__ import annotations


class VisionOcrEngine:
    """Cloud Vision `document_text_detection` を使う OCR。認証は ADC。"""

    def recognize(self, image_bytes: bytes) -> str:
        from google.cloud import vision

        client = vision.ImageAnnotatorClient()
        image = vision.Image(content=image_bytes)
        # 日本語ヒントを与えると認識精度が上がる。
        context = vision.ImageContext(language_hints=["ja"])
        response = client.document_text_detection(image=image, image_context=context)
        if response.error.message:
            raise RuntimeError(f"Cloud Vision error: {response.error.message}")
        return response.full_text_annotation.text or ""


__all__ = ["VisionOcrEngine"]
