"""Observability ライブラリ。

- `tracer`: OpenTelemetry TracerProvider の初期化 (Phoenix / Langfuse への OTLP 送信)
- `context`: 現在の trace_id / span_id を W3C 形式で取り出す
- `logger`: structlog を trace_id 自動注入付きで設定する
- `schemas`: 業務ログ JSONL の Pydantic discriminated union (`event_type` を discriminator)
- `content`: 大きなコンテンツを inline / URI 参照に振り分ける
- `hashing`: `sha256:<hex>` 形式のハッシュ生成
- `analytics_logger`: AnalyticsLogger 本体。バリデーション + バッファ + 非同期フラッシュ
- `sinks`: JSONL を Hive パーティション形式で書き出すシンク
"""
