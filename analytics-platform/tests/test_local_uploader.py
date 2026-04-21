from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from observability.sinks.file_sink import RotatingFileSink
from uploader.local_uploader import LocalMoveTransport, LocalUploader


async def _seed_raw(tmp_path: Path, n: int = 3) -> RotatingFileSink:
    sink = RotatingFileSink(root_dir=tmp_path / "raw", service_name="svc")
    ts = datetime(2026, 4, 20, 10, 0, tzinfo=UTC)
    await sink.write_batch(
        [
            '{"event_id":"'
            + str(i)
            + '","event_type":"llm_call","event_timestamp":"'
            + ts.isoformat()
            + '"}'
            for i in range(n)
        ]
    )
    return sink


async def test_run_once_moves_all_successful(tmp_path: Path) -> None:
    await _seed_raw(tmp_path, n=2)

    uploader = LocalUploader(
        raw_root=tmp_path / "raw",
        uploaded_root=tmp_path / "uploaded",
        dead_letter_root=tmp_path / "dead_letter",
        transport=LocalMoveTransport(raw_root=tmp_path / "raw"),
    )
    outcome = await uploader.run_once()
    assert len(outcome.uploaded) == 1  # 1 ファイル (複数行はあっても同じシャード)
    assert outcome.dead_letter == []
    assert not list((tmp_path / "raw").rglob("*.jsonl"))
    assert list((tmp_path / "uploaded").rglob("*.jsonl"))


async def test_run_once_dead_letters_on_failure(tmp_path: Path) -> None:
    await _seed_raw(tmp_path, n=1)

    # 常に失敗するトランスポート
    class AlwaysFail:
        async def send(self, src: Path, *, dest_root: Path) -> Path:
            raise OSError("nope")

    uploader = LocalUploader(
        raw_root=tmp_path / "raw",
        uploaded_root=tmp_path / "uploaded",
        dead_letter_root=tmp_path / "dead_letter",
        transport=AlwaysFail(),
        max_attempts=2,
        backoff_multiplier=0.0,
        backoff_max=0.0,
    )
    outcome = await uploader.run_once()
    assert outcome.uploaded == []
    assert len(outcome.dead_letter) == 1
    assert list((tmp_path / "dead_letter").rglob("*.jsonl"))


async def test_empty_raw_dir_noop(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    uploader = LocalUploader(
        raw_root=tmp_path / "raw",
        uploaded_root=tmp_path / "uploaded",
        dead_letter_root=tmp_path / "dead_letter",
        transport=LocalMoveTransport(raw_root=tmp_path / "raw"),
    )
    outcome = await uploader.run_once()
    assert outcome.uploaded == []
    assert outcome.dead_letter == []
