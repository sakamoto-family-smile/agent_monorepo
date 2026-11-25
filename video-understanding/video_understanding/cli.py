"""video-understanding の CLI。"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

from . import api, cache
from .config import Config, ConfigError, load_config
from .fetch import FetchError
from .frames import FramesError
from .source import SourceError

USER_ERRORS = (api.InputError, ConfigError, FetchError, FramesError, SourceError)


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="video-understanding", description="動画をコマ一覧画像と字幕にする"
    )
    sub = ap.add_subparsers(dest="command", required=True)

    ov = sub.add_parser("overview", help="情報・字幕・全体のコマ一覧画像")
    ov.add_argument("source", help="YouTube の URL か、許可ディレクトリ内の動画ファイル")
    ov.add_argument("--interval", type=float, help="コマの間隔 (秒)。省略時は長さから自動")
    ov.add_argument("--lang", default="ja", help="字幕の言語 (既定 ja)")
    ov.add_argument("--out", type=Path, help="一覧画像をこのディレクトリにも書き出す")

    fr = sub.add_parser("frames", help="区間のコマを細かく取り出す")
    fr.add_argument("source")
    fr.add_argument("--start", type=float, required=True, help="開始 (秒)")
    fr.add_argument("--end", type=float, required=True, help="終了 (秒)")
    fr.add_argument("--fps", type=float, default=10, help="1 秒あたりのコマ数 (既定 10、最大 30)")
    fr.add_argument("--crop", help="x,y,w,h を 0〜1 の比率で (例: 0.2,0,0.6,1)")
    fr.add_argument("--out", type=Path)

    tr = sub.add_parser("transcript", help="時刻つきの字幕か文字起こしの全文")
    tr.add_argument("source")
    tr.add_argument("--lang", default="ja", help="言語 (既定 ja)")
    tr.add_argument(
        "--force-whisper", action="store_true", help="字幕があっても音声を文字起こしする"
    )

    gc = sub.add_parser("gc", help="最終利用から期限を過ぎた動画本体・コマを消す")
    gc.add_argument("--dry-run", action="store_true", help="消すものを表示するだけ")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap


def _copy_out(sheets: list[Path], out: Path | None) -> list[Path]:
    if out is None:
        return sheets
    out.mkdir(parents=True, exist_ok=True)
    return [Path(shutil.copy2(s, out / s.name)) for s in sheets]


def _gc(cfg: Config, dry_run: bool) -> None:
    r = cache.gc(cfg.cache_dir, cfg.video_ttl_days, dry_run=dry_run)
    verb = "消す予定" if dry_run else "消しました"
    print(
        f"{cfg.video_ttl_days} 日使われていない動画: {len(r.expired)} 本 ({r.freed_bytes / 1e6:.1f} MB) を{verb}"
    )
    for d in r.expired:
        print(f"  {d}")


def _dispatch(args: argparse.Namespace, cfg: Config) -> None:
    if args.command == "transcript":
        print(
            api.render_transcript(api.transcript(args.source, cfg, args.lang, args.force_whisper))
        )
        return
    if args.command == "gc":
        _gc(cfg, args.dry_run)
        return
    if args.command == "overview":
        result = api.overview(args.source, cfg, interval=args.interval, lang=args.lang)
        print(api.render_overview(result))
    else:
        result = api.frames(args.source, cfg, args.start, args.end, args.fps, args.crop)
        print(api.render_frames(result))
    if args.out:
        print("書き出し先:", *_copy_out(result.sheets, args.out), sep="\n  ")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        _dispatch(args, load_config())
    except USER_ERRORS as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
