"""edinet-client: EDINET API v2 ラッパ (proposal 0006)。

主要型 / クラス:
- `EdinetClient`: EDINET API v2 の async HTTP client
- `Cache` (Protocol) / `LocalCache` / `GcsCache` / `InMemoryCache`: 書類本体 cache
- `EdinetCodeResolver`: ticker (証券コード) ⇔ EDINET code マッピング
- `DocumentMetadata` / `DocumentBody` / `DocumentType`: Pydantic 型

Phase 1a (PR #156): HTTP client + types + LocalCache + tests
Phase 1b (PR #157): code_resolver (ticker → EDINET code、 285A 対応)
Phase 1c (本 PR): GcsCache 実装 (Cloud Run 用)
"""

from edinet_client.cache import Cache, ContentType, GcsCache, InMemoryCache, LocalCache
from edinet_client.client import EdinetClient
from edinet_client.code_resolver import EdinetCodeRecord, EdinetCodeResolver
from edinet_client.types import (
    DisclosureStatus,
    DocumentBody,
    DocumentMetadata,
    DocumentType,
    WithdrawalStatus,
)

__version__ = "0.3.0"

__all__ = [
    "Cache",
    "ContentType",
    "DisclosureStatus",
    "DocumentBody",
    "DocumentMetadata",
    "DocumentType",
    "EdinetClient",
    "EdinetCodeRecord",
    "EdinetCodeResolver",
    "GcsCache",
    "InMemoryCache",
    "LocalCache",
    "WithdrawalStatus",
    "__version__",
]
