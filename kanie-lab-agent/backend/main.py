import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import firebase_admin
from firebase_admin import credentials

from routes.chat import router as chat_router
from routes.sessions import router as sessions_router
from routes.notes import router as notes_router
from config import settings


def validate_config() -> None:
    """本番環境の必須設定を起動時に検証する"""
    if settings.app_env != "local":
        frontend_url = os.getenv("FRONTEND_URL", "")
        if not frontend_url:
            raise RuntimeError(
                "FRONTEND_URL must be set in non-local environments"
            )


def init_firebase():
    """Firebase Admin SDKを初期化する"""
    if firebase_admin._apps:
        return

    auth_emulator = os.getenv("FIREBASE_AUTH_EMULATOR_HOST")
    firestore_emulator = os.getenv("FIRESTORE_EMULATOR_HOST")

    if auth_emulator or firestore_emulator:
        # エミュレーター環境
        app = firebase_admin.initialize_app(
            options={"projectId": os.getenv("FIREBASE_PROJECT_ID", "demo-kanie-lab")}
        )
    else:
        # 本番環境
        cred = credentials.ApplicationDefault()
        app = firebase_admin.initialize_app(cred)

    return app


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_config()
    init_firebase()
    yield


app = FastAPI(
    title="蟹江研究室 大学院入試準備エージェント API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(chat_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")
app.include_router(notes_router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "kanie-lab-backend"}
