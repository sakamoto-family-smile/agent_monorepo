"""Phase 3: Vertex Gemini を使った相談・分析エージェント。

責務:
- ユーザの自然言語入力を Gemini に渡し、tool_use loop を回して回答テキストを返す
- 各メッセージを SessionRepo + analytics-platform に保存
- emergency_gate と connecting する (本モジュールは consulting mode 想定で
  emergency check は line_handler 側で先に実施する前提)
- LLM 失敗 / 未設定時は graceful fallback (テキストで通知)

使い方:
    consultant = Consultation(
        repo=event_repo,
        session_repo=session_repo,
        analytics_logger=al,
        family_id="f1",
        line_user_id="U1",
    )
    reply = await consultant.respond("2月と3月のミルク量を比較して")

Vertex 未設定 (PIYOLOG_VERTEX_PROJECT 空) なら CONSULT_NOT_CONFIGURED を返す。
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from config import settings
from repositories.session_repo import (
    GAP_ASKED_CLARIFICATION,
    GAP_COMPLETED,
    GAP_REFUSED,
    GAP_TOOL_ERROR,
    ROLE_ASSISTANT,
    ROLE_TOOL_RESULT,
    ROLE_TOOL_USE,
    ROLE_USER,
    SessionRepo,
)
from services.context_builder import build_recent_context
from services.tool_executor import execute_tool
from services.tools import TOOLS

logger = logging.getLogger(__name__)


SYSTEM_PROMPT_VERSION = "v1"

SYSTEM_PROMPT = """\
あなたはぴよログ (育児記録アプリ) のデータをもとに、家族の質問に答える日本語アシスタントです。

# 役割
- 家族の育児ログ (ミルク・睡眠・排泄・体重等) について、自然言語の質問に応答する
- 必要なら `query_events` tool を呼んで具体的なデータを取得し、要約して回答する
- 質問が曖昧な場合は `ask_clarification` tool を呼んで具体的な質問をユーザに返す
- 育児に関する一般的な相談 (生活リズム・離乳食・授乳間隔等) にも、家族のデータを踏まえて答える

# 重要な制約
- **医療診断はしない**。発熱・症状・薬等の質問には「医師受診を検討」と促す
- **断定的な評価はしない** ("少なすぎ" "異常" 等は避ける)。「〇〇という傾向です」「相談を検討するなら」等の柔らかい表現
- **エビデンスを過大評価しない**。家族 1 件のデータから医学的結論は出さない
- **個人情報を求めない** (氏名・住所・他者の情報等)
- ユーザが緊急の症状を訴えた場合は「#8000 / 119 へ」と促す

# tool 利用方針
- ユーザが具体的な期間・指標を聞いてきた → query_events で取得 → 自然な日本語で要約
- 比較したい質問 ("X月とY月を比較") → query_events を 2 回呼んで両方取得
- どの単位 (回数 / ml 量) を聞きたいか曖昧 → ask_clarification を呼ぶ
- 1 つの質問で tool は最大 5 回まで。それで足りなければユーザに追加情報を求める

# 出力フォーマット
- 短く要点だけ (LINE 表示前提、4900 文字以内)
- 数値は単位付き ("120 ml" "8 時間")
- 必要なら箇条書き
"""


CONSULT_NOT_CONFIGURED = (
    "💬 相談機能は現在、サーバ側の設定 (Vertex AI) が完了していないため利用できません。"
)

CONSULT_FALLBACK_ERROR = "申し訳ありません、回答生成中にエラーが発生しました。少し時間を置いてからもう一度お試しください。"


class Consultation:
    """1 ユーザの 1 conversation を扱うステートレスなクライアント。"""

    def __init__(
        self,
        *,
        repo,
        session_repo: SessionRepo,
        analytics_logger,
        family_id: str,
        line_user_id: str,
        llm_client: GeminiClient | None = None,
        child_repo=None,
        child_id: str = "default",
    ) -> None:
        self._repo = repo
        self._session_repo = session_repo
        self._al = analytics_logger
        self._family_id = family_id
        self._line_user_id = line_user_id
        # llm_client が None なら lazy 構築 (テストで差し替え可能)
        self._llm = llm_client
        # Phase 4-B: 子情報 DB (env が空なら DB から month-age を再構築)
        self._child_repo = child_repo
        self._child_id = child_id

    async def respond(self, user_message: str) -> str:
        """ユーザの 1 発話を処理し、最終応答テキストを返す。

        - conversation を取得 or 開始
        - 履歴 + RECENT CONTEXT + system prompt を Gemini に投げる
        - tool_use があればループで実行
        - 全メッセージを SessionRepo に append、analytics-platform に emit
        """
        if not settings.vertex_configured:
            return CONSULT_NOT_CONFIGURED

        if self._llm is None:
            try:
                self._llm = build_default_llm_client()
            except Exception:
                logger.exception("failed to build LLM client")
                return CONSULT_FALLBACK_ERROR

        # 既存 conversation を継続 or 新規開始
        sess = await self._session_repo.get_session(line_user_id=self._line_user_id)
        if sess and sess.current_conversation_id:
            cid = sess.current_conversation_id
        else:
            conv = await self._session_repo.start_conversation(
                family_id=self._family_id,
                line_user_id=self._line_user_id,
                system_prompt_version=SYSTEM_PROMPT_VERSION,
            )
            cid = conv.conversation_id
            self._emit_consultation_started(cid, trigger="text_command")

        # ユーザメッセージを保存 + 計測
        await self._session_repo.append_message(
            conversation_id=cid, role=ROLE_USER, content=user_message
        )
        self._emit_message(cid, role=ROLE_USER, content=user_message)

        # context + 履歴
        recent_ctx = await build_recent_context(
            repo=self._repo,
            family_id=self._family_id,
            child_repo=self._child_repo,
            child_id=self._child_id,
        )
        history = await self._session_repo.fetch_history(
            conversation_id=cid, limit=settings.vertex_history_window
        )
        # Gemini messages format に変換 (現時点では text + tool のみ)
        gemini_messages: list[dict[str, Any]] = []
        for m in history:
            if m.role == ROLE_USER:
                gemini_messages.append({"role": "user", "content": m.content})
            elif m.role == ROLE_ASSISTANT:
                gemini_messages.append({"role": "model", "content": m.content})
            elif m.role == ROLE_TOOL_USE:
                gemini_messages.append({"role": "tool_use", "content": m.content})
            elif m.role == ROLE_TOOL_RESULT:
                gemini_messages.append({"role": "tool_result", "content": m.content})

        # tool use loop
        try:
            final_text, capability_gap = await self._tool_use_loop(
                cid=cid,
                system_prompt=SYSTEM_PROMPT,
                recent_context=recent_ctx,
                messages=gemini_messages,
            )
        except Exception:
            logger.exception("LLM tool_use loop failed")
            return CONSULT_FALLBACK_ERROR

        # 最終 assistant メッセージを保存
        await self._session_repo.append_message(
            conversation_id=cid,
            role=ROLE_ASSISTANT,
            content=final_text,
            llm_model=settings.vertex_model,
            capability_gap=capability_gap,
        )
        self._emit_message(
            cid,
            role=ROLE_ASSISTANT,
            content=final_text,
            capability_gap=capability_gap,
        )
        return final_text

    async def _tool_use_loop(
        self,
        *,
        cid: str,
        system_prompt: str,
        recent_context: str,
        messages: list[dict[str, Any]],
    ) -> tuple[str, str]:
        """Gemini を呼び、tool 要求があれば実行して再投入。最終テキストと gap を返す。"""
        capability_gap = GAP_COMPLETED
        for iteration in range(settings.vertex_max_tool_iterations):
            response = await self._llm.generate(
                system_prompt=system_prompt,
                recent_context=recent_context,
                messages=messages,
                tools=TOOLS,
                max_output_tokens=settings.vertex_max_output_tokens,
                temperature=settings.vertex_temperature,
            )
            if response.tool_calls:
                # 各 tool を実行 → 結果を append して loop 継続
                for tc in response.tool_calls:
                    # tool_use を保存
                    tool_use_payload = json.dumps(
                        {"tool": tc.name, "args": tc.args}, ensure_ascii=False
                    )
                    await self._session_repo.append_message(
                        conversation_id=cid,
                        role=ROLE_TOOL_USE,
                        content=tool_use_payload,
                        tool_name=tc.name,
                    )
                    self._emit_message(
                        cid, role=ROLE_TOOL_USE, content=tool_use_payload, tool_name=tc.name
                    )
                    # 実行
                    try:
                        result_str = await execute_tool(
                            name=tc.name,
                            args=tc.args,
                            repo=self._repo,
                            family_id=self._family_id,
                        )
                    except Exception as exc:
                        logger.exception("tool execution failed")
                        result_str = json.dumps(
                            {"error": str(exc), "tool": tc.name},
                            ensure_ascii=False,
                        )
                        capability_gap = GAP_TOOL_ERROR
                    await self._session_repo.append_message(
                        conversation_id=cid,
                        role=ROLE_TOOL_RESULT,
                        content=result_str,
                        tool_name=tc.name,
                    )
                    self._emit_message(
                        cid,
                        role=ROLE_TOOL_RESULT,
                        content=result_str,
                        tool_name=tc.name,
                    )
                    # ask_clarification なら早期 return (LLM の質問をそのままユーザに返す)
                    if tc.name == "ask_clarification":
                        try:
                            payload = json.loads(result_str)
                            return payload.get(
                                "question", "詳しく教えてください。"
                            ), GAP_ASKED_CLARIFICATION
                        except Exception:
                            return "詳しく教えてください。", GAP_ASKED_CLARIFICATION
                    # それ以外: messages に追加して loop 継続
                    messages.append({"role": "tool_use", "content": tool_use_payload})
                    messages.append({"role": "tool_result", "content": result_str})
                continue  # 次の iteration で LLM に再問合せ
            # tool_calls なし: text 応答完了
            return response.text or "", capability_gap

        # 最大 iteration 到達
        logger.warning("tool_use loop hit max iterations (cid=%s)", cid)
        return "回答に時間がかかりました。もう少し具体的に質問してください。", GAP_REFUSED

    # ---- analytics-platform emit ----

    def _emit_consultation_started(self, cid: str, *, trigger: str) -> None:
        try:
            self._al.emit(
                event_type="business_event",
                event_version="1.0.0",
                severity="INFO",
                fields={
                    "business_domain": "piyolog",
                    "action": "consultation_started",
                    "resource_type": "conversation",
                    "resource_id": cid,
                    "attributes": {
                        "trigger": trigger,
                        "family_id": self._family_id,
                        "system_prompt_version": SYSTEM_PROMPT_VERSION,
                    },
                },
                user_id=self._line_user_id,
                session_id=cid,
            )
        except Exception:
            logger.exception("failed to emit consultation_started")

    def _emit_message(
        self,
        cid: str,
        *,
        role: str,
        content: str,
        tool_name: str | None = None,
        capability_gap: str | None = None,
    ) -> None:
        """生メッセージは BigQuery に送らない (PII)。ハッシュ + 文字数 + メタのみ。"""
        try:
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
            self._al.emit(
                event_type="business_event",
                event_version="1.0.0",
                severity="INFO",
                fields={
                    "business_domain": "piyolog",
                    "action": "consultation_message_emitted",
                    "resource_type": "conversation",
                    "resource_id": cid,
                    "attributes": {
                        "role": role,
                        "tool_name": tool_name,
                        "capability_gap": capability_gap,
                        "content_hash": content_hash,
                        "content_chars": len(content),
                        "family_id": self._family_id,
                    },
                },
                user_id=self._line_user_id,
                session_id=cid,
            )
        except Exception:
            logger.exception("failed to emit consultation_message_emitted")

    def emit_consultation_ended(self, cid: str, *, ended_by: str) -> None:
        """conversation 終了時に外部から呼ぶ用 (mode 切替時等)。"""
        try:
            self._al.emit(
                event_type="business_event",
                event_version="1.0.0",
                severity="INFO",
                fields={
                    "business_domain": "piyolog",
                    "action": "consultation_ended",
                    "resource_type": "conversation",
                    "resource_id": cid,
                    "attributes": {
                        "ended_by": ended_by,
                        "family_id": self._family_id,
                    },
                },
                user_id=self._line_user_id,
                session_id=cid,
            )
        except Exception:
            logger.exception("failed to emit consultation_ended")


# ---- Vertex Gemini クライアント (薄いラッパ。テストで差替可) ----


class ToolCall:
    """LLM が要求した 1 つの tool 呼び出し。"""

    __slots__ = ("name", "args")

    def __init__(self, name: str, args: dict[str, Any]) -> None:
        self.name = name
        self.args = args


class LLMResponse:
    """generate() が返す統一型。tool_calls が non-empty なら text は無視。"""

    __slots__ = ("text", "tool_calls", "input_tokens", "output_tokens")

    def __init__(
        self,
        *,
        text: str,
        tool_calls: list[ToolCall] | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        self.text = text
        self.tool_calls = tool_calls or []
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class GeminiClient:
    """Vertex AI Gemini を呼び出す薄いラッパ。

    生成パラメータは generate() 引数で。tool_use の Gemini-API スキーマ↔
    LLMResponse 変換も担う。実装は遅延 import で起動時にコストを払わない。
    """

    def __init__(self, *, project: str, location: str, model: str) -> None:
        self._project = project
        self._location = location
        self._model = model
        self._initialized = False
        self._gen_model = None

    def _initialize(self) -> None:
        if self._initialized:
            return
        from vertexai import generative_models, init  # type: ignore[import]

        init(project=self._project, location=self._location)
        self._gm_module = generative_models
        self._initialized = True

    async def generate(
        self,
        *,
        system_prompt: str,
        recent_context: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_output_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        self._initialize()
        gm = self._gm_module
        # Vertex Gemini のメッセージ形式に変換
        # 各 message は {role: user|model|tool_use|tool_result, content: str}
        # tool 結果は user role に function_response として埋め込むのが Gemini 流儀
        # 簡易実装: history を 1 つの user message として渡し、tool は declarative に
        # 渡す (PoC レベル)。実用では Gemini の Content/Part 構造に正しく合わせる。
        contents = []
        # SYSTEM + RECENT CONTEXT を user の最初のターンに混ぜる
        intro = "[SYSTEM]\n" + system_prompt + "\n\n[RECENT_CONTEXT]\n" + recent_context
        contents.append({"role": "user", "parts": [{"text": intro}]})
        contents.append(
            {
                "role": "model",
                "parts": [{"text": "了解しました。質問をどうぞ。"}],
            }
        )
        for m in messages:
            role = m.get("role", "user")
            if role == "model":
                contents.append({"role": "model", "parts": [{"text": m["content"]}]})
            elif role in ("tool_use", "tool_result"):
                # tool 履歴は LLM コンテキストに含める (Gemini は user に function_call/response を期待するが、
                # テキスト埋込でも動く。PoC レベルで OK。)
                contents.append({"role": "user", "parts": [{"text": f"[{role}] {m['content']}"}]})
            else:
                contents.append({"role": "user", "parts": [{"text": m["content"]}]})

        tool_decl = self._build_tools(tools)
        gen_config = gm.GenerationConfig(
            max_output_tokens=max_output_tokens,
            temperature=temperature,
        )
        if self._gen_model is None:
            self._gen_model = gm.GenerativeModel(model_name=self._model)

        # Vertex SDK の generate_content_async を使う
        result = await self._gen_model.generate_content_async(
            contents=contents,
            generation_config=gen_config,
            tools=[tool_decl] if tool_decl else None,
        )
        return self._parse_response(result)

    def _build_tools(self, tools: list[dict[str, Any]]):
        """tools dict を Vertex SDK の Tool オブジェクトに変換。"""
        gm = self._gm_module
        decls = []
        for t in tools:
            decls.append(
                gm.FunctionDeclaration(
                    name=t["name"],
                    description=t["description"],
                    parameters=t["parameters"],
                )
            )
        if not decls:
            return None
        return gm.Tool(function_declarations=decls)

    def _parse_response(self, result: Any) -> LLMResponse:
        """Vertex SDK の GenerateContentResponse を統一型に変換。"""
        text = ""
        tool_calls: list[ToolCall] = []
        try:
            candidates = getattr(result, "candidates", None) or []
            if candidates:
                content = getattr(candidates[0], "content", None)
                parts = getattr(content, "parts", []) if content else []
                for part in parts:
                    fn_call = getattr(part, "function_call", None)
                    if fn_call and getattr(fn_call, "name", None):
                        # args は MapComposite 等の場合があるので dict に変換
                        args = dict(fn_call.args) if fn_call.args else {}
                        tool_calls.append(ToolCall(fn_call.name, args))
                    else:
                        ptext = getattr(part, "text", None)
                        if ptext:
                            text += ptext
        except Exception:
            logger.exception("failed to parse Gemini response")

        usage = getattr(result, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
        output_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


def build_default_llm_client() -> GeminiClient:
    """settings から GeminiClient を構築。"""
    if not settings.vertex_configured:
        raise RuntimeError("vertex_project not configured")
    return GeminiClient(
        project=settings.vertex_project,
        location=settings.vertex_location,
        model=settings.vertex_model,
    )


__all__ = [
    "CONSULT_FALLBACK_ERROR",
    "CONSULT_NOT_CONFIGURED",
    "Consultation",
    "GeminiClient",
    "LLMResponse",
    "SYSTEM_PROMPT",
    "SYSTEM_PROMPT_VERSION",
    "ToolCall",
    "build_default_llm_client",
]
