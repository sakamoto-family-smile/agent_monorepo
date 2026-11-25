"""環境変数から設定を読む。"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ENV_PREFIX = "VIDEO_UNDERSTANDING_"
DEFAULT_CACHE_DIR = Path("~/.cache/video-understanding")
DEFAULT_VIDEO_TTL_DAYS = 14
DEFAULT_MAX_DURATION_SEC = 1800
DEFAULT_WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
# 文字起こしの用語ヒント (whisper の initial_prompt)。ゴルフのレッスン動画で崩れやすい言葉を並べる
DEFAULT_WHISPER_PROMPT = (
    "ゴルフスイングのレッスン動画です。アドレス、テークバック、トップ、切り返し、ダウンスイング、"
    "インパクト、フォロースルー、フィニッシュ、体重移動、左足、右足、骨盤、股関節、捻転、"
    "ハンドファースト、フェース、シャフト、クラブ、ドライバー、アイアン、ウェッジ、ヘッドスピード。"
)


class ConfigError(ValueError):
    """環境変数の値がおかしい。"""


@dataclass(frozen=True)
class Config:
    cache_dir: Path
    allowed_dirs: tuple[Path, ...]
    video_ttl_days: int
    max_duration_sec: int
    whisper_model: str = DEFAULT_WHISPER_MODEL
    whisper_prompt: str = DEFAULT_WHISPER_PROMPT


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(ENV_PREFIX + name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as e:
        raise ConfigError(f"{ENV_PREFIX}{name} は整数で指定してください: {raw!r}") from e
    if value <= 0:
        raise ConfigError(f"{ENV_PREFIX}{name} は 1 以上で指定してください: {value}")
    return value


def load_config(env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    cache_raw = env.get(ENV_PREFIX + "CACHE_DIR", "").strip()
    cache_dir = Path(cache_raw).expanduser() if cache_raw else DEFAULT_CACHE_DIR.expanduser()
    allowed = tuple(
        Path(p).expanduser()
        for p in env.get(ENV_PREFIX + "ALLOWED_DIRS", "").split(":")
        if p.strip()
    )
    return Config(
        cache_dir=cache_dir,
        allowed_dirs=allowed,
        video_ttl_days=_positive_int(env, "VIDEO_TTL_DAYS", DEFAULT_VIDEO_TTL_DAYS),
        max_duration_sec=_positive_int(env, "MAX_DURATION_SEC", DEFAULT_MAX_DURATION_SEC),
        whisper_model=env.get(ENV_PREFIX + "WHISPER_MODEL", "").strip() or DEFAULT_WHISPER_MODEL,
        # 空文字を明示すればヒント無しにできる
        whisper_prompt=env.get(ENV_PREFIX + "WHISPER_PROMPT", DEFAULT_WHISPER_PROMPT).strip(),
    )
