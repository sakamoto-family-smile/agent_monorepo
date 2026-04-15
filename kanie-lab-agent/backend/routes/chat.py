import json
import logging
import uuid
from typing import Optional, List
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import StreamingResponse
from middleware.auth import verify_firebase_token
from services.agent import run_agent
from services import firestore as fs
from services.file_parser import extract_text, build_file_context
from claude_agent_sdk import AssistantMessage, ResultMessage, ToolUseBlock

logger = logging.getLogger(__name__)

router = APIRouter()

# ツール名 → 日本語ステータスメッセージのマッピング
_TOOL_STATUS_MAP = [
    # Claude Code ビルトインツール
    ("WebSearch",         "🌐 Web検索中..."),
    ("WebFetch",          "📡 Webページを取得中..."),
    ("ToolSearch",        "🔧 ツールを検索中..."),
    # ファイル操作
    ("Read",              "📂 ファイルを読み込み中..."),
    ("Glob",              "🔎 ファイルを検索中..."),
    ("Grep",              "🔎 コードを検索中..."),
    # MCP ツール（設定時に対応）
    ("mcp__paper-search", "📄 論文データベースを検索中..."),
    ("mcp__arxiv",        "📑 arXiv論文を検索中..."),
    ("mcp__semantic-scholar", "🔬 論文引用ネットワークを分析中..."),
    ("mcp__brave-search", "🌐 Web検索中（英語）..."),
    ("mcp__google-search","🔍 Google検索中..."),
    ("mcp__fetch",        "📡 Webページを取得中..."),
    ("mcp__estat",        "📊 政府統計データを検索中..."),
    ("mcp__e-gov-law",    "⚖️ 法令データを検索中..."),
]


def _tool_status_message(tool_name: str) -> str:
    for prefix, msg in _TOOL_STATUS_MAP:
        if tool_name.startswith(prefix):
            return msg
    return f"⚙️ {tool_name} を実行中..."


@router.post("/chat")
async def chat(
    request: Request,
    message: str = Form(...),
    session_id: Optional[str] = Form(None),
    mode: str = Form("research"),
    files: List[UploadFile] = File(default=[]),
    uid: str = Depends(verify_firebase_token),
):
    """チャットエンドポイント: SSEストリームでエージェントの応答を返す"""
    if not message and not files:
        return {"error": "メッセージが空です"}

    # 添付ファイルのテキストを抽出してプロンプトに追記
    full_message = message
    for f in files:
        if not f.filename:
            continue
        try:
            text = await extract_text(f)
            full_message += build_file_context(f.filename, text)
        except ValueError as e:
            logger.warning("file_parser skipped %s: %s", f.filename, e)

    async def stream():
        new_session_id = session_id
        try:
            async for msg in run_agent(full_message, uid, mode, session_id):
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, ToolUseBlock):
                            status = _tool_status_message(block.name)
                            data = {"type": "status", "message": status, "tool": block.name}
                            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

                    text_parts = [
                        block.text
                        for block in msg.content
                        if hasattr(block, "text")
                    ]
                    if text_parts:
                        data = {"type": "text", "content": "".join(text_parts)}
                        yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

                elif isinstance(msg, ResultMessage):
                    new_session_id = msg.session_id or str(uuid.uuid4())
                    title = message[:50] + ("..." if len(message) > 50 else "")
                    try:
                        await fs.create_or_update_session(uid, new_session_id, title, mode)
                        await fs.save_message(uid, new_session_id, "user", message)
                        if msg.result:
                            await fs.save_message(uid, new_session_id, "assistant", msg.result)
                    except Exception:
                        pass  # Firestore 未起動時はスキップ

                    data = {"type": "done", "session_id": new_session_id}
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        except TimeoutError as e:
            logger.warning("chat stream timeout: %s", e)
            data = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.exception("chat stream error: %s", e)
            data = {"type": "error", "message": f"エラーが発生しました: {e}"}
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
