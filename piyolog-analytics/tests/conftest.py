"""pytest 共通 fixture。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# app/ を sys.path に追加
APP_DIR = Path(__file__).resolve().parent.parent / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


# テスト中は外部呼出し不能状態にする
os.environ.setdefault("LINE_CHANNEL_SECRET", "")
os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "")
os.environ.setdefault("FAMILY_USER_IDS", "Utest1,Utest2")
