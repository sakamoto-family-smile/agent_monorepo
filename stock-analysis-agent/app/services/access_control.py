"""PROPOSAL-0011 P1: アクセス制御 (allow-list) と分析レート制限。

LINE webhook は任意 IP から POST される public エンドポイントのため、署名検証に
加えて **userId allow-list** で家族以外を弾く。さらに Claude Opus 分析は従量課金が
高いため、1 ユーザ 1 日あたりの `分析` 回数に上限を設ける。

MVP はプロセス内メモリでカウントする (再起動でリセット)。永続的な制限が要れば
Phase 2 で Cloud SQL / Firestore に移す。
"""

from __future__ import annotations

import threading
import time

import config  # settings は毎回 lookup (test isolation / database.py と同方針)


def is_user_allowed(user_id: str) -> bool:
    """allow-list 判定。`FAMILY_USER_IDS` 未設定なら全許可 (dev)。"""
    allowed = config.settings.family_user_id_set
    if not allowed:
        return True
    return user_id in allowed


class DailyRateLimiter:
    """(user_id, UTC 日) 単位の日次カウンタ。スレッドセーフ。"""

    _SECONDS_PER_DAY = 86_400

    def __init__(self, limit_per_day: int) -> None:
        self._limit = limit_per_day
        self._lock = threading.Lock()
        # key: (user_id, day_index) -> count
        self._counts: dict[tuple[str, int], int] = {}

    def _day_index(self, now: float) -> int:
        return int(now // self._SECONDS_PER_DAY)

    def check_and_increment(self, user_id: str) -> bool:
        """上限内なら count を 1 増やして True、超過なら False を返す。

        `limit <= 0` は無制限扱い。
        """
        if self._limit <= 0:
            return True
        now = time.time()
        day = self._day_index(now)
        with self._lock:
            # 古い日のエントリを掃除 (メモリ肥大防止)
            stale = [k for k in self._counts if k[1] != day]
            for k in stale:
                self._counts.pop(k, None)
            key = (user_id, day)
            current = self._counts.get(key, 0)
            if current >= self._limit:
                return False
            self._counts[key] = current + 1
            return True


_analyze_limiter: DailyRateLimiter | None = None


def get_analyze_limiter() -> DailyRateLimiter:
    global _analyze_limiter
    if _analyze_limiter is None:
        _analyze_limiter = DailyRateLimiter(config.settings.analyze_rate_limit_per_day)
    return _analyze_limiter


def reset_analyze_limiter() -> None:
    """テスト用 reset。"""
    global _analyze_limiter
    _analyze_limiter = None


__all__ = [
    "is_user_allowed",
    "DailyRateLimiter",
    "get_analyze_limiter",
    "reset_analyze_limiter",
]
