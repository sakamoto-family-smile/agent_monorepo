"""取得停止などの監視項目 (FR-I07)。

- intel:<source>: 情報源ごとの最終成功が取得間隔の STALE_FACTOR 倍より古い
- detection:scan: 照合の最終成功が照合間隔の STALE_FACTOR 倍より古い
- sbom:<service>: 本番イメージの SBOM (make detection-images) が IMAGE_SBOM_MAX_AGE_DAYS より古い

どれも各サービスの DB・ファイルを読み取り専用で見るだけ。状態が変わったときの通知は pipeline が行う。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError

from ..common.timeutil import parse_iso
from ..detection.images import read_manifest
from ..intel.schedule import STALE_FACTOR


@dataclass(frozen=True)
class Check:
    key: str
    ok: bool
    detail: str


def _age(now: datetime, last: datetime | None) -> str:
    if last is None:
        return "成功の記録なし"
    hours = (now - last).total_seconds() / 3600
    return f"最終成功 {hours:.0f} 時間前" if hours < 48 else f"最終成功 {hours / 24:.0f} 日前"


def _last(engine: Engine, sql: str, params: dict[str, str]) -> datetime | None:
    with engine.connect() as conn:
        v = conn.execute(text(sql), params).scalar()
    return parse_iso(v) if v else None


def intel_checks(engine: Engine | None, schedule: dict[str, timedelta], now: datetime) -> list[Check]:
    if engine is None:
        return [Check("intel", False, "intel.db がありません")]
    out = []
    for source, interval in schedule.items():
        try:
            last = _last(engine, "SELECT MAX(finished_at) FROM source_runs WHERE source = :s AND status = 'success'",
                         {"s": source})
        except OperationalError as e:
            return [Check("intel", False, f"intel.db を読めません ({e.orig})")]
        ok = last is not None and now - last < interval * STALE_FACTOR
        out.append(Check(f"intel:{source}", ok, _age(now, last)))
    return out


def detection_checks(
    engine: Engine | None, scan_interval: timedelta, sbom_dir: Path, sbom_max_age: timedelta, now: datetime,
) -> list[Check]:
    if engine is None:
        return [Check("detection", False, "detection.db がありません")]
    try:
        last = _last(engine, "SELECT MAX(finished_at) FROM scan_runs WHERE job = :j AND status = 'success'",
                     {"j": "scan"})
        with engine.connect() as conn:
            services = conn.execute(text("SELECT service_id, config_json FROM services ORDER BY service_id")).all()
    except OperationalError as e:
        return [Check("detection", False, f"detection.db を読めません ({e.orig})")]
    out = [Check("detection:scan", last is not None and now - last < scan_interval * STALE_FACTOR, _age(now, last))]
    for service_id, config in services:
        if not json.loads(config).get("images"):
            continue
        try:
            manifest = read_manifest(sbom_dir, service_id)
        except ValueError as e:
            out.append(Check(f"sbom:{service_id}", False, str(e)))
            continue
        generated = parse_iso(manifest["generated_at"]) if manifest and manifest.get("generated_at") else None
        ok = generated is not None and now - generated <= sbom_max_age
        detail = "SBOM がありません" if generated is None else f"SBOM 作成 {(now - generated).days} 日前"
        out.append(Check(f"sbom:{service_id}", ok, f"{detail} (make detection-images)"))
    return out
