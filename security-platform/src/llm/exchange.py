"""intel と extractor のファイルのやり取り (data/llm/)。

    in/<job_id>.json   intel が書く。抽出してほしい記事 1 件 (extractor は読み取り専用でマウントする)
    out/<job_id>.json  extractor が書く。抽出の結果 1 件。intel が取り込んだら in と一緒に消す

job_id は記事と本文のハッシュから決める (本文が変わったら別の job になる)。
書き込みは一時ファイルからの rename で、読み手が書きかけのファイルを見ないようにする。
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schema import ExtractInput

FORMAT = 1
JOB_ID = re.compile(r"^rep_[0-9a-f]{24}-[0-9a-f]{12}$")
MAX_JOB_BYTES = 200_000


def job_id(report_id: str, content_hash: str) -> str:
    return f"{report_id}-{content_hash[:12]}"


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _read(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_JOB_BYTES:
        raise ValueError(f"{path.name} is larger than {MAX_JOB_BYTES} bytes")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError(f"{path.name}: unknown format")
    return data


def list_ids(directory: Path) -> list[str]:
    """古い順 (更新時刻) の job_id。名前が job_id の形でないファイルは無視する。"""
    if not directory.is_dir():
        return []
    files = [p for p in directory.glob("*.json") if JOB_ID.match(p.stem)]
    return [p.stem for p in sorted(files, key=lambda p: (p.stat().st_mtime, p.name))]


# ── in ──────────────────────────────────────────────────────────────────
def write_job(in_dir: Path, item: ExtractInput) -> None:
    write_json(in_dir / f"{item.job_id}.json", {
        "format": FORMAT, "job_id": item.job_id, "report_id": item.report_id,
        "content_hash": item.content_hash, "title": item.title, "url": item.url, "text": item.text,
    })


def read_job(in_dir: Path, jid: str) -> ExtractInput:
    d = _read(in_dir / f"{jid}.json")
    if d.get("job_id") != jid or job_id(str(d.get("report_id")), str(d.get("content_hash"))) != jid:
        raise ValueError(f"{jid}: job_id does not match its content")
    return ExtractInput(jid, d["report_id"], d["content_hash"], str(d["title"]), d.get("url"), str(d["text"]))


# ── out ─────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class JobResult:
    job_id: str
    provider: str
    model: str
    prompt_version: str
    finished_at: str
    output: dict[str, Any] | None  # 失敗したときは None
    error: str | None = None


def write_result(out_dir: Path, r: JobResult) -> None:
    write_json(out_dir / f"{r.job_id}.json", {"format": FORMAT, **r.__dict__})


def read_result(out_dir: Path, jid: str) -> JobResult:
    d = _read(out_dir / f"{jid}.json")
    if d.get("job_id") != jid:
        raise ValueError(f"{jid}: job_id does not match")
    return JobResult(jid, str(d["provider"]), str(d["model"]), str(d["prompt_version"]), str(d["finished_at"]),
                     d.get("output"), d.get("error"))
