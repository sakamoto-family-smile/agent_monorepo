/**
 * SSE（Server-Sent Events）ストリーミング処理
 * バックエンドのチャットAPIからリアルタイムで応答を受け取る
 */

export interface SSETextEvent {
  type: "text";
  content: string;
}

export interface SSEDoneEvent {
  type: "done";
  session_id: string;
}

export interface SSEErrorEvent {
  type: "error";
  message: string;
}

export interface SSEStatusEvent {
  type: "status";
  message: string;
  tool: string;
}

export type SSEEvent = SSETextEvent | SSEDoneEvent | SSEErrorEvent | SSEStatusEvent;

interface StreamChatOptions {
  message: string;
  files?: File[];
  sessionId?: string | null;
  mode: string;
  token: string;
  onText: (text: string) => void;
  onDone: (sessionId: string) => void;
  onError: (message: string) => void;
  onStatus?: (message: string, tool: string) => void;
}

/**
 * チャットAPIにPOSTしてSSEストリームを受け取る
 * ファイルが添付されている場合は multipart/form-data、それ以外は JSON で送信する
 */
export async function streamChat(options: StreamChatOptions): Promise<void> {
  const { message, files, sessionId, mode, token, onText, onDone, onError, onStatus } = options;

  // ファイルがある場合は FormData、なければ JSON
  let body: FormData | string;
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };

  if (files && files.length > 0) {
    const formData = new FormData();
    formData.append("message", message);
    formData.append("mode", mode);
    if (sessionId) formData.append("session_id", sessionId);
    files.forEach((f) => formData.append("files", f));
    body = formData;
    // Content-Type は FormData に任せる（boundary が自動付与される）
  } else {
    body = JSON.stringify({ message, session_id: sessionId, mode });
    headers["Content-Type"] = "application/json";
  }

  let response: Response;

  try {
    response = await fetch("/api/chat", {
      method: "POST",
      headers,
      body,
    });
  } catch {
    onError("ネットワークエラーが発生しました。接続を確認してください。");
    return;
  }

  if (!response.ok) {
    onError(`サーバーエラー: ${response.status}`);
    return;
  }

  if (!response.body) {
    onError("レスポンスボディが空です");
    return;
  }

  // ReadableStreamでSSEを読み込む
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSEの形式: "data: {...}\n\n"
      const lines = buffer.split("\n\n");
      buffer = lines.pop() || "";

      for (const chunk of lines) {
        const line = chunk.trim();
        if (!line.startsWith("data: ")) continue;

        const jsonStr = line.slice(6);
        try {
          const event: SSEEvent = JSON.parse(jsonStr);

          switch (event.type) {
            case "text":
              onText(event.content);
              break;
            case "done":
              onDone(event.session_id);
              break;
            case "error":
              onError(event.message);
              break;
            case "status":
              onStatus?.(event.message, event.tool);
              break;
          }
        } catch {
          console.warn("SSEイベント解析エラー:", jsonStr);
        }
      }
    }
  } catch (err) {
    if (err instanceof Error && err.name !== "AbortError") {
      onError("ストリームの読み込み中にエラーが発生しました");
    }
  } finally {
    reader.releaseLock();
  }
}
