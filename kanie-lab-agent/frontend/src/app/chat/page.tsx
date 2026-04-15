"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { ChatWindow } from "@/components/ChatWindow";
import { SessionList } from "@/components/SessionList";
import { useChat } from "@/hooks/useChat";

export default function ChatPage() {
  const router = useRouter();
  const { user, loading: authLoading, signOut } = useAuth();
  const {
    sessions, currentSessionId, messages, mode,
    isStreaming, streamingStatus, loadSessions, selectSession,
    startNewSession, setMode, sendMessage,
  } = useChat();

  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    if (!authLoading && !user) router.push("/");
  }, [user, authLoading, router]);

  useEffect(() => {
    if (user) loadSessions();
  }, [user, loadSessions]);

  if (authLoading) {
    return (
      <div
        className="min-h-screen w-full flex items-center justify-center"
        style={{ background: "#05080f" }}
      >
        <div className="flex gap-2">
          <span className="w-2 h-2 rounded-full bg-amber-400 dot-1" />
          <span className="w-2 h-2 rounded-full bg-amber-400 dot-2" />
          <span className="w-2 h-2 rounded-full bg-amber-400 dot-3" />
        </div>
      </div>
    );
  }

  if (!user) return null;

  const sidebarContent = (
    <div className="flex flex-col h-full">
      {/* アプリ名 */}
      <div
        className="px-4 py-4 flex items-center justify-between flex-shrink-0"
        style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold flex-shrink-0"
            style={{
              background: "rgba(245,158,11,0.12)",
              border: "1px solid rgba(245,158,11,0.28)",
              color: "#fbbf24",
            }}
          >
            蟹
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold truncate" style={{ color: "#f1f5f9" }}>
              蟹江研究室
            </p>
            <p className="text-xs" style={{ color: "#475569" }}>AI 入試準備</p>
          </div>
        </div>
        {/* モバイル閉じるボタン */}
        <button
          className="lg:hidden p-1.5 rounded-lg transition-colors flex-shrink-0"
          style={{ color: "#475569" }}
          onClick={() => setSidebarOpen(false)}
          aria-label="サイドバーを閉じる"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* セッション一覧 */}
      <div className="flex-1 overflow-hidden">
        <SessionList
          sessions={sessions}
          currentSessionId={currentSessionId}
          onSelectSession={(id) => { selectSession(id); setSidebarOpen(false); }}
          onNewSession={() => { startNewSession(); setSidebarOpen(false); }}
        />
      </div>

      {/* ユーザー情報 */}
      <div
        className="px-4 py-3 flex items-center gap-2.5 flex-shrink-0"
        style={{ borderTop: "1px solid rgba(255,255,255,0.06)" }}
      >
        <div
          className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0"
          style={{
            background: "linear-gradient(135deg, rgba(245,158,11,0.2), rgba(245,158,11,0.1))",
            border: "1px solid rgba(245,158,11,0.25)",
            color: "#fbbf24",
          }}
        >
          {user.email?.[0]?.toUpperCase() ?? "U"}
        </div>
        <p className="text-xs flex-1 truncate" style={{ color: "#64748b" }}>
          {user.email}
        </p>
        <button
          onClick={async () => { await signOut(); router.push("/"); }}
          className="text-xs transition-colors flex-shrink-0 px-2 py-1 rounded-md"
          style={{ color: "#475569" }}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = "#94a3b8";
            e.currentTarget.style.background = "rgba(255,255,255,0.05)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = "#475569";
            e.currentTarget.style.background = "transparent";
          }}
        >
          ログアウト
        </button>
      </div>
    </div>
  );

  return (
    <div
      className="flex h-screen w-screen overflow-hidden"
      style={{ background: "#07090f" }}
    >
      {/* モバイルオーバーレイ */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-20 lg:hidden"
          style={{ background: "rgba(0,0,0,0.6)", backdropFilter: "blur(4px)" }}
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* サイドバー */}
      <aside
        className={[
          "flex-shrink-0 flex flex-col z-30 transition-transform duration-300",
          "lg:relative lg:translate-x-0 lg:w-60",
          "fixed inset-y-0 left-0 w-72",
          sidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
        ].join(" ")}
        style={{
          background: "linear-gradient(180deg, #07090f 0%, #0a0f1c 100%)",
          borderRight: "1px solid rgba(255,255,255,0.06)",
        }}
      >
        {sidebarContent}
      </aside>

      {/* メインエリア */}
      <main className="flex-1 flex flex-col overflow-hidden min-w-0">
        {/* モバイルヘッダー */}
        <div
          className="lg:hidden flex items-center gap-3 px-4 py-3 flex-shrink-0"
          style={{
            background: "rgba(7,9,15,0.95)",
            borderBottom: "1px solid rgba(255,255,255,0.06)",
            backdropFilter: "blur(12px)",
          }}
        >
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-1.5 rounded-lg transition-colors"
            style={{ color: "#64748b" }}
            aria-label="メニューを開く"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <span className="text-sm font-medium" style={{ color: "#94a3b8" }}>
            蟹江研究室 入試準備
          </span>
        </div>

        <ChatWindow
          messages={messages}
          mode={mode}
          isStreaming={isStreaming}
          streamingStatus={streamingStatus}
          onSendMessage={sendMessage}
          onModeChange={setMode}
        />
      </main>
    </div>
  );
}
