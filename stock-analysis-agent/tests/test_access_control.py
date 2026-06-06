"""アクセス制御 (allow-list) と分析レート制限の unit テスト。

config の `settings` は module-level singleton。importlib.reload すると別オブジェクトに
分裂し他テストを壊すため、ここでは共有 singleton の属性を monkeypatch するだけにする。
"""

from __future__ import annotations

import services.access_control as ac
from services.access_control import DailyRateLimiter


def test_allow_all_when_family_ids_empty(monkeypatch):
    monkeypatch.setattr(ac.settings, "family_user_ids", "")
    assert ac.is_user_allowed("U_anyone") is True


def test_only_listed_users_allowed(monkeypatch):
    monkeypatch.setattr(ac.settings, "family_user_ids", "U_alice, U_bob")
    assert ac.is_user_allowed("U_alice") is True
    assert ac.is_user_allowed("U_bob") is True
    assert ac.is_user_allowed("U_eve") is False


def test_rate_limiter_blocks_after_limit():
    limiter = DailyRateLimiter(2)
    assert limiter.check_and_increment("U_a") is True
    assert limiter.check_and_increment("U_a") is True
    assert limiter.check_and_increment("U_a") is False
    # 別ユーザは独立カウント
    assert limiter.check_and_increment("U_b") is True


def test_rate_limiter_unlimited_when_zero():
    limiter = DailyRateLimiter(0)
    for _ in range(100):
        assert limiter.check_and_increment("U_a") is True
