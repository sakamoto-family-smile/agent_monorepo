import os
import re
from fastapi import Request, HTTPException
from firebase_admin import auth

# demo-<uid> トークンで許可される UID 形式（英数字・ハイフンのみ）
_SAFE_UID_RE = re.compile(r"^[a-zA-Z0-9\-]{1,128}$")


async def verify_firebase_token(request: Request) -> str:
    """Firebase IDトークンを検証し、uidを返す"""
    is_emulator = bool(os.getenv("FIREBASE_AUTH_EMULATOR_HOST"))
    is_local = os.getenv("APP_ENV") == "local"

    # エミュレーターバイパスはローカル開発環境のみ有効
    # 両方の条件が揃っている場合のみバイパスを許可
    if is_emulator and is_local:
        authorization = request.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            token = authorization.split("Bearer ")[1]
            if token.startswith("demo-"):
                uid = token[len("demo-"):]
                # パストラバーサル等の危険な文字を含む UID を拒否
                if not _SAFE_UID_RE.match(uid):
                    raise HTTPException(status_code=401, detail="無効なデモトークンです")
                return uid
            try:
                decoded = auth.verify_id_token(token)
                return decoded["uid"]
            except Exception:
                raise HTTPException(status_code=401, detail="無効な認証トークンです")
        raise HTTPException(status_code=401, detail="認証トークンがありません")

    authorization = request.headers.get("Authorization")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="認証トークンがありません")

    token = authorization.split("Bearer ")[1]
    try:
        decoded = auth.verify_id_token(token)
        return decoded["uid"]
    except Exception:
        raise HTTPException(status_code=401, detail="無効な認証トークンです")
