"""resolver: 表記ゆれ吸収。

藤沢市の保育施設名は表記ゆれが多発する:

  - 中黒 (なかぐろ「・」) の有無: 例「キディ鵠沼・藤沢」⇔「キディ鵠沼藤沢」
  - 分園表記の有無
  - 旧名 → 新名 (改名) など

fuzzy match + alias dict で正規化する。マッチング処理フロー詳細は
`facility_resolver.py` の module docstring を参照。

設計の根拠は proposal 0003 §4.4 / 0005 §38.5 を参照。
"""

from fujisawa_platform.resolver.facility_resolver import (
    Candidate,
    FacilityResolver,
    NoMatchError,
    ResolverEntry,
)

__all__ = [
    "Candidate",
    "FacilityResolver",
    "NoMatchError",
    "ResolverEntry",
]
