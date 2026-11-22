"""設定 (環境変数から読む)。

秘密情報 (LINE のチャンネルシークレット・アクセストークン) は config/local.env に置き、
docker compose の env_file で backend にだけ渡す。
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_TZ = "Asia/Tokyo"
# push の月の上限。LINE の無料の通数 (コミュニケーションプランで月 200 通) より余裕を持たせる (§4.3.2)
DEFAULT_PUSH_MONTHLY_LIMIT = 150


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def db(self) -> Path:
        return self.root / "golf.db"

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def media(self) -> Path:
        return self.root / "media"

    @property
    def backup(self) -> Path:
        return self.root / "backup"

    @property
    def tmp(self) -> Path:
        return self.root / "tmp"

    def ensure(self) -> None:
        for path in (self.root, self.raw, self.media, self.backup, self.tmp):
            path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Settings:
    app_env: str
    paths: Paths
    line_channel_secret: str
    line_channel_access_token: str
    # 許可する LINE userId (自分だけ)。空なら誰からのメッセージも保存しない
    allowed_user_ids: frozenset[str]
    tz: ZoneInfo
    push_monthly_limit: int = DEFAULT_PUSH_MONTHLY_LIMIT

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        ids = frozenset(v.strip() for v in env.get("ALLOWED_USER_IDS", "").split(",") if v.strip())
        return cls(
            app_env=env.get("APP_ENV", "dev"),
            paths=Paths(Path(env.get("GOLF_DATA_DIR", "data"))),
            line_channel_secret=env.get("LINE_CHANNEL_SECRET", ""),
            line_channel_access_token=env.get("LINE_CHANNEL_ACCESS_TOKEN", ""),
            allowed_user_ids=ids,
            tz=ZoneInfo(env.get("TZ_NAME", DEFAULT_TZ)),
            push_monthly_limit=int(env.get("PUSH_MONTHLY_LIMIT", str(DEFAULT_PUSH_MONTHLY_LIMIT))),
        )
