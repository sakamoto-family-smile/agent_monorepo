import { auth } from "./firebase";

// APIベースURL（Next.jsのrewritesを通じてバックエンドにプロキシ）
const API_BASE = "/api";

/**
 * 認証済みFetch: Firebaseトークンを自動付与する
 */
async function authFetch(
  path: string,
  options: RequestInit = {}
): Promise<Response> {
  const user = auth.currentUser;
  let token = "";

  if (user) {
    try {
      token = await user.getIdToken();
    } catch {
      // トークン取得失敗時は空のトークンで続行（エミュレーター環境用）
      token = "demo-local-test-user";
    }
  } else {
    // 未ログイン時はデモトークンを使用（開発用）
    token = "demo-local-test-user";
  }

  return fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...options.headers,
    },
  });
}

// セッション一覧の型
export interface Session {
  id: string;
  title: string;
  mode: string;
  updated_at: unknown;
  created_at: unknown;
}

// メッセージの型
export interface ApiMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: unknown;
}

/**
 * セッション一覧を取得する
 */
export async function getSessions(): Promise<Session[]> {
  const res = await authFetch("/sessions");
  if (!res.ok) {
    throw new Error(`セッション取得エラー: ${res.status}`);
  }
  const data = await res.json();
  return data.sessions || [];
}

/**
 * 特定セッションのメッセージを取得する
 */
export async function getSessionMessages(
  sessionId: string
): Promise<ApiMessage[]> {
  const res = await authFetch(`/sessions/${sessionId}`);
  if (!res.ok) {
    throw new Error(`メッセージ取得エラー: ${res.status}`);
  }
  const data = await res.json();
  return data.messages || [];
}

/**
 * セッションを削除する
 */
export async function deleteSession(sessionId: string): Promise<void> {
  const res = await authFetch(`/sessions/${sessionId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(`セッション削除エラー: ${res.status}`);
  }
}

/**
 * チャットを開始する（SSEストリームのURLとトークンを準備）
 * 実際のSSE接続はsse.tsのstreamChatを使用する
 */
export async function getChatToken(): Promise<string> {
  const user = auth.currentUser;
  if (user) {
    try {
      return await user.getIdToken();
    } catch {
      return "demo-local-test-user";
    }
  }
  return "demo-local-test-user";
}
