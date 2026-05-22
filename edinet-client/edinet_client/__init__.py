"""edinet-client: EDINET API v2 ラッパ (proposal 0006)。

主要型 / クラス:
- `EdinetClient`: EDINET API v2 の async HTTP client
- `Cache` (Protocol) / `LocalCache` / `InMemoryCache`: 書類本体 cache
- `DocumentMetadata` / `DocumentBody` / `DocumentType`: Pydantic 型

Phase 1a (本 PR): HTTP client + types + LocalCache + tests
Phase 1b: code_resolver (ticker → EDINET code)
Phase 1c: GcsCache 実装
"""

from edinet_client.cache import Cache, ContentType, InMemoryCache, LocalCache
from edinet_client.client import EdinetClient
from edinet_client.types import (
    DisclosureStatus,
    DocumentBody,
    DocumentMetadata,
    DocumentType,
    WithdrawalStatus,
)

__version__ = "0.1.0"

__all__ = [
    "Cache",
    "ContentType",
    "DisclosureStatus",
    "DocumentBody",
    "DocumentMetadata",
    "DocumentType",
    "EdinetClient",
    "InMemoryCache",
    "LocalCache",
    "WithdrawalStatus",
    "__version__",
]
