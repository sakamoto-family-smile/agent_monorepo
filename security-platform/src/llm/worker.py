"""extractor の処理: data/llm/in/ の記事を LLM にかけ、data/llm/out/ に結果を書く。

- 1 日に LLM を呼ぶ回数は daily_limit まで (Max プランの上限は対話の利用と共有なので、使い切らない)
- 常駐では夜 (run_hour 時から window_hours 時間) だけ動く
- 認証の失敗・利用上限 (ProviderUnavailable) ではその回を止め、記事は in に残して次の夜にやり直す
- 1 件ごとの失敗 (ExtractionFailed) は結果として書き、intel が回数を数えてやり直す
状態 (その日の回数・最後に止まった理由) は state/usage.json に書く (notify が監視に使う)。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..common.timeutil import to_iso
from .exchange import JobResult, list_ids, read_job, write_json, write_result
from .providers import ExtractionFailed, Extractor, ProviderUnavailable
from .schema import PROMPT_VERSION

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_FAILURES = 3  # 続けて失敗したら、記事ではなく LLM 側の問題とみなして止める


@dataclass(frozen=True)
class LlmDirs:
    in_dir: Path
    out_dir: Path
    state_dir: Path

    @property
    def usage_path(self) -> Path:
        return self.state_dir / "usage.json"


@dataclass(frozen=True)
class Window:
    daily_limit: int = 50
    run_hour: int = 3
    window_hours: int = 3
    timezone: str = "Asia/Tokyo"

    def local(self, now: datetime) -> datetime:
        return now.astimezone(ZoneInfo(self.timezone))

    def is_open(self, now: datetime) -> bool:
        hour = self.local(now).hour
        return (hour - self.run_hour) % 24 < self.window_hours


@dataclass
class BatchResult:
    done: int = 0
    failed: int = 0
    pending: int = 0
    stopped: str | None = None
    errors: list[str] = field(default_factory=list)


def read_usage(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def run_batch(extractor: Extractor, dirs: LlmDirs, window: Window, now: datetime,
              limit: int | None = None) -> BatchResult:
    """in にあって out にない記事を古い順に処理する。limit はその日の残り回数よりさらに絞るときに使う。"""
    today = window.local(now).date().isoformat()
    usage = read_usage(dirs.usage_path)
    used = int(usage.get("count", 0)) if usage.get("date") == today else 0  # type: ignore[call-overload]
    allowed = window.daily_limit - used if limit is None else min(limit, window.daily_limit - used)
    todo = [j for j in list_ids(dirs.in_dir) if not (dirs.out_dir / f"{j}.json").exists()]
    r = BatchResult()
    consecutive = 0
    for jid in todo:
        if r.done + r.failed >= allowed:
            break
        try:
            item = read_job(dirs.in_dir, jid)
        except (ValueError, KeyError, OSError) as e:  # intel が書いたファイルが壊れている。LLM は呼ばない
            write_result(dirs.out_dir, JobResult(jid, extractor.provider, extractor.model, PROMPT_VERSION,
                                                 to_iso(now), None, f"unreadable job: {e}"[:500]))
            r.failed += 1
            continue
        try:
            output, error = extractor.extract(item), None
            consecutive = 0
        except ProviderUnavailable as e:
            r.stopped = str(e)[:500]
            break
        except ExtractionFailed as e:
            output, error = None, str(e)[:500]
            consecutive += 1
        write_result(dirs.out_dir, JobResult(jid, extractor.provider, extractor.model, PROMPT_VERSION,
                                             to_iso(now), output, error))
        used += 1
        if error:
            r.failed += 1
            r.errors.append(f"{jid}: {error}")
            logger.warning("extract failed: %s: %s", jid, error)
        else:
            r.done += 1
        usage = {**usage, "date": today, "count": used}  # 途中で落ちても回数が残るよう 1 件ごとに書く
        write_json(dirs.usage_path, usage)
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            r.stopped = f"{consecutive} failures in a row; last: {error}"[:500]
            break
    r.pending = len(todo) - r.done - r.failed
    write_json(dirs.usage_path, {
        **usage, "date": today, "count": used, "last_run_at": to_iso(now),
        "last_stopped": r.stopped, "provider": extractor.provider, "model": extractor.model,
    })
    if r.stopped:
        logger.error("extract stopped: %s (%d pending; retried in the next window)", r.stopped, r.pending)
    logger.info("extract: %d done, %d failed, %d pending, %d/%d used today",
                r.done, r.failed, r.pending, used, window.daily_limit)
    return r
