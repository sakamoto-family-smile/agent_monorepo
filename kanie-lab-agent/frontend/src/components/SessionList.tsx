"use client";

interface Session {
  id: string;
  title: string;
  mode: string;
  updated_at: unknown;
}

interface SessionListProps {
  sessions: Session[];
  currentSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onNewSession: () => void;
}

const MODE_LABELS: Record<string, string> = {
  research:  "研究",
  survey:    "論文",
  interview: "面接",
  review:    "レビュー",
};

const MODE_DOT: Record<string, string> = {
  research:  "#60a5fa",
  survey:    "#34d399",
  interview: "#fb923c",
  review:    "#c084fc",
};

export function SessionList({ sessions, currentSessionId, onSelectSession, onNewSession }: SessionListProps) {
  return (
    <div className="flex flex-col h-full">
      {/* 新規ボタン */}
      <div className="px-3 py-3">
        <button
          onClick={onNewSession}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium transition-all duration-150"
          style={{
            background: "rgba(245,158,11,0.1)",
            border: "1px solid rgba(245,158,11,0.25)",
            color: "#fbbf24",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(245,158,11,0.18)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(245,158,11,0.1)"; }}
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          新しい会話
        </button>
      </div>

      {/* 一覧 */}
      <nav aria-label="チャット履歴" className="flex-1 overflow-y-auto px-2 pb-2">
        {sessions.length === 0 ? (
          <p className="text-center text-xs py-8 px-3" style={{ color: "#475569" }}>
            まだ会話がありません
          </p>
        ) : (
          <ul className="space-y-0.5">
            {sessions.map((session) => {
              const isActive = currentSessionId === session.id;
              return (
                <li key={session.id}>
                  <button
                    onClick={() => onSelectSession(session.id)}
                    aria-current={isActive ? "page" : undefined}
                    className="w-full text-left px-3 py-2.5 rounded-lg transition-all duration-150"
                    style={{
                      background: isActive ? "rgba(255,255,255,0.1)" : "transparent",
                      border: isActive ? "1px solid rgba(255,255,255,0.1)" : "1px solid transparent",
                    }}
                    onMouseEnter={(e) => {
                      if (!isActive) e.currentTarget.style.background = "rgba(255,255,255,0.06)";
                    }}
                    onMouseLeave={(e) => {
                      if (!isActive) e.currentTarget.style.background = "transparent";
                    }}
                  >
                    <span className="flex items-center gap-1.5 mb-0.5">
                      <span
                        className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                        style={{ background: MODE_DOT[session.mode] ?? "#94a3b8" }}
                      />
                      <span className="text-xs" style={{ color: "#64748b" }}>
                        {MODE_LABELS[session.mode] ?? session.mode}
                      </span>
                    </span>
                    <span
                      className="block text-xs leading-snug line-clamp-2"
                      style={{ color: isActive ? "#e2e8f0" : "#94a3b8" }}
                    >
                      {session.title || "（タイトルなし）"}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </nav>
    </div>
  );
}
