"""resolver: 表記ゆれ吸収。

藤沢市の保育施設名は表記ゆれ (中黒の有無、分園表記、名称変更等) が多発するため、
fuzzy match + alias dict で正規化する。

詳細は proposal 0003 §4.4 / 0005 §38.5 を参照。
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
