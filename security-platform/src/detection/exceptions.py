"""Finding の例外 (誤検知・リスク受容)。

例外はモノレポ (public) には置かず detection.db にだけ持つ。理由付きの一覧は
「受け入れたリスクの一覧」になり、公開すると攻撃の手がかりになるため。
``make detection-exceptions ARGS="add ..."`` で登録し、照合のたびに当てはめる。

- service: サービス ID か ``*`` (全サービス)
- advisory: Advisory の ID (CVE 番号など)
- package: パッケージ名。省略するとその Advisory の全パッケージ
- kind: ``false_positive`` (誤検知) / ``risk_accepted`` (影響を理解した上で受け入れる)。
  リスク受容は期限 (最長 MAX_RISK_DAYS 日) が必須。期限が来たら Finding は open に戻る
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import Engine, text

from ..common.timeutil import parse_iso, to_iso, utc_now

Kind = Literal["false_positive", "risk_accepted"]
KINDS: tuple[str, ...] = ("false_positive", "risk_accepted")
ANY_SERVICE = "*"
MAX_RISK_DAYS = 180


@dataclass(frozen=True)
class FindingException:
    exception_id: str
    service_id: str
    advisory_id: str
    package: str | None
    kind: str
    reason: str
    expires_at: datetime | None
    created_at: datetime
    revoked_at: datetime | None = None

    def active(self, now: datetime) -> bool:
        return self.revoked_at is None and (self.expires_at is None or now < self.expires_at)

    def covers(self, service_id: str, advisory_id: str, package: str) -> bool:
        return (
            self.service_id in (ANY_SERVICE, service_id)
            and self.advisory_id == advisory_id
            and (self.package is None or self.package.lower() == package.lower())
        )


def validate(kind: str, reason: str, expires_at: datetime | None, now: datetime) -> None:
    if kind not in KINDS:
        raise ValueError(f"kind は {' / '.join(KINDS)} のどちらか")
    if not reason.strip():
        raise ValueError("理由 (reason) は必須")
    if expires_at is not None and expires_at <= now:
        raise ValueError("期限 (expires) が過去になっています")
    if kind == "risk_accepted":
        if expires_at is None:
            raise ValueError("risk_accepted は期限 (expires) が必須")
        if expires_at - now > timedelta(days=MAX_RISK_DAYS):
            raise ValueError(f"risk_accepted の期限は {MAX_RISK_DAYS} 日以内")


class ExceptionStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def add(
        self, service_id: str, advisory_id: str, package: str | None, kind: str, reason: str,
        expires_at: datetime | None, now: datetime | None = None,
    ) -> FindingException:
        now = now or utc_now()
        validate(kind, reason, expires_at, now)
        key = f"{service_id}\n{advisory_id}\n{package or ''}\n{to_iso(now)}"
        exc = FindingException(
            "exc_" + hashlib.sha256(key.encode()).hexdigest()[:16], service_id, advisory_id,
            package or None, kind, reason.strip(), expires_at, now,
        )
        with self.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO exceptions (exception_id, service_id, advisory_id, purl, package, kind, reason,
                  expires_at, created_at)
                VALUES (:id, :s, :a, NULL, :p, :k, :r, :e, :c)
            """), {"id": exc.exception_id, "s": service_id, "a": advisory_id, "p": exc.package, "k": kind,
                   "r": exc.reason, "e": to_iso(expires_at) if expires_at else None, "c": to_iso(now)})
        return exc

    def revoke(self, exception_id: str, now: datetime | None = None) -> bool:
        with self.engine.begin() as conn:
            n = conn.execute(
                text("UPDATE exceptions SET revoked_at = :t WHERE exception_id = :id AND revoked_at IS NULL"),
                {"t": to_iso(now or utc_now()), "id": exception_id},
            ).rowcount
        return n == 1

    def all(self) -> list[FindingException]:
        with self.engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT exception_id, service_id, advisory_id, package, kind, reason, expires_at, created_at, "
                "revoked_at FROM exceptions ORDER BY created_at"
            )).all()
        return [
            FindingException(r[0], r[1], r[2], r[3], r[4], r[5], parse_iso(r[6]) if r[6] else None,
                             parse_iso(r[7]), parse_iso(r[8]) if r[8] else None)
            for r in rows
        ]

    def active(self, now: datetime) -> list[FindingException]:
        return [e for e in self.all() if e.active(now)]


def find_exception(
    exceptions: list[FindingException], service_id: str, advisory_id: str, package: str,
) -> FindingException | None:
    return next((e for e in exceptions if e.covers(service_id, advisory_id, package)), None)
