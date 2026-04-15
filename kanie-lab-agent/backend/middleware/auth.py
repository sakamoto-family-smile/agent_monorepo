import os
from fastapi import Request, HTTPException
from firebase_admin import auth


async def verify_firebase_token(request: Request) -> str:
    """Firebase IDトークンを検証し、uidを返す"""
    # エミュレーター環境では認証をバイパス（開発用）
    if os.getenv("FIREBASE_AUTH_EMULATOR_HOST") and os.getenv("APP_ENV") == "local":
        # Authorization ヘッダーからuid直接取得（開発用）
        authorization = request.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            token = authorization.split("Bearer ")[1]
            # エミュレータートークンは検証をスキップ
            if token.startswith("demo-"):
                return token.replace("demo-", "")
            try:
                decoded = auth.verify_id_token(token)
                return decoded["uid"]
            except Exception:
                # エミュレーター環境ではフォールバック
                return "local-test-user"
        return "local-test-user"

    authorization = request.headers.get("Authorization")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="認証トークンがありません")

    token = authorization.split("Bearer ")[1]
    try:
        decoded = auth.verify_id_token(token)
        return decoded["uid"]
    except Exception:
        raise HTTPException(status_code=401, detail="無効な認証トークンです")
