"use client";

import { useRef, useEffect, useState, useCallback } from "react";
import { MessageBubble, type Message } from "./MessageBubble";
import { ModeSelector, type AgentMode } from "./ModeSelector";

interface ChatWindowProps {
  messages: Message[];
  mode: AgentMode;
  isStreaming: boolean;
  streamingStatus: string;
  onSendMessage: (message: string, files?: File[]) => void;
  onModeChange: (mode: AgentMode) => void;
}

const SUGGESTIONS: { text: string; mode: AgentMode; icon: string; color: string }[] = [
  { text: "SDGsと子ども政策を組み合わせた研究テーマを考えたい", mode: "research", icon: "🔍", color: "#60a5fa" },
  { text: "SDGsガバナンスに関する先行研究を調べて",             mode: "survey",   icon: "📚", color: "#34d399" },
  { text: "研究計画について模擬面接を実施してほしい",             mode: "interview", icon: "🎤", color: "#fb923c" },
  { text: "作成した研究計画書をレビューしてほしい",               mode: "review",   icon: "✍️", color: "#c084fc" },
];

const MODE_PLACEHOLDERS: Record<AgentMode, string> = {
  research:  "研究テーマについて相談する...",
  survey:    "サーベイしたい論文テーマを入力...",
  interview: "面接練習を始める...",
  review:    "レビューしてほしい研究計画を貼り付け...",
};

const ACCEPTED_TYPES = ".txt,.md,.csv,.docx,.pdf";

/** ファイルサイズを人間が読みやすい単位に変換 */
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function ChatWindow({ messages, mode, isStreaming, streamingStatus, onSendMessage, onModeChange }: ChatWindowProps) {
  const [inputValue, setInputValue] = useState("");
  const [attachedFiles, setAttachedFiles] = useState<File[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const adjustHeight = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const msg = inputValue.trim();
    if ((!msg && attachedFiles.length === 0) || isStreaming) return;
    setInputValue("");
    setAttachedFiles([]);
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    onSendMessage(msg, attachedFiles.length > 0 ? attachedFiles : undefined);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSubmit(e); }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files ?? []);
    setAttachedFiles((prev) => {
      // 同名ファイルは上書き
      const names = new Set(selected.map((f) => f.name));
      const deduped = prev.filter((f) => !names.has(f.name));
      return [...deduped, ...selected];
    });
    // 同じファイルを再選択できるようにリセット
    e.target.value = "";
  };

  const removeFile = (name: string) => {
    setAttachedFiles((prev) => prev.filter((f) => f.name !== name));
  };

  const canSend = (!!inputValue.trim() || attachedFiles.length > 0) && !isStreaming;

  return (
    <div
      className="flex flex-col h-full"
      style={{ background: "linear-gradient(180deg, #07090f 0%, #090c14 100%)" }}
    >
      {/* ── ツールバー ── */}
      <div
        className="px-5 py-3 flex-shrink-0"
        style={{
          background: "rgba(7,9,15,0.8)",
          borderBottom: "1px solid rgba(255,255,255,0.06)",
          backdropFilter: "blur(12px)",
        }}
      >
        <ModeSelector currentMode={mode} onChange={onModeChange} disabled={isStreaming} />
      </div>

      {/* ── メッセージエリア ── */}
      <section
        aria-label="チャットメッセージ"
        className="flex-1 overflow-y-auto px-4 py-6 sm:px-6"
      >
        {messages.length === 0 ? (
          /* 空状態 */
          <div className="h-full flex flex-col items-center justify-center text-center max-w-xl mx-auto">
            {/* ロゴ */}
            <div
              className="w-14 h-14 rounded-2xl flex items-center justify-center text-xl font-bold mb-5"
              style={{
                background: "linear-gradient(135deg, rgba(30,58,95,0.9), rgba(15,23,42,0.9))",
                border: "1px solid rgba(245,158,11,0.25)",
                boxShadow: "0 0 32px rgba(245,158,11,0.1), inset 0 1px 0 rgba(255,255,255,0.08)",
                color: "#fbbf24",
              }}
            >
              蟹
            </div>
            <h2 className="text-base font-semibold mb-1.5" style={{ color: "#e2e8f0" }}>
              何から始めますか？
            </h2>
            <p className="text-sm leading-relaxed mb-8" style={{ color: "#475569" }}>
              モードを選択するか、カードをクリックして会話を開始できます。
            </p>

            {/* サジェスションカード */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s.text}
                  onClick={() => { onModeChange(s.mode); onSendMessage(s.text); }}
                  disabled={isStreaming}
                  className="text-left p-4 rounded-xl transition-all duration-150 disabled:opacity-50 group"
                  style={{
                    background: "rgba(255,255,255,0.03)",
                    border: "1px solid rgba(255,255,255,0.07)",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = `${s.color}0a`;
                    e.currentTarget.style.borderColor = `${s.color}35`;
                    e.currentTarget.style.boxShadow = `0 4px 20px ${s.color}10`;
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "rgba(255,255,255,0.03)";
                    e.currentTarget.style.borderColor = "rgba(255,255,255,0.07)";
                    e.currentTarget.style.boxShadow = "none";
                  }}
                >
                  <span className="text-lg mb-2 block">{s.icon}</span>
                  <span className="text-xs leading-relaxed" style={{ color: "#94a3b8" }}>
                    {s.text}
                  </span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          /* メッセージリスト */
          <div className="space-y-5 max-w-3xl mx-auto w-full">
            {messages.map((m) => <MessageBubble key={m.id} message={m} />)}

            {/* ストリーミング中インジケーター（テキスト未着信の間のみ表示） */}
            {isStreaming && messages[messages.length - 1]?.role !== "assistant" && (
              <div
                className="py-5 message-enter"
                style={{ borderBottom: "1px solid rgba(255,255,255,0.05)" }}
                aria-label="回答生成中"
              >
                <div className="flex items-center gap-2 mb-2">
                  <div
                    className="w-[18px] h-[18px] rounded-[4px] flex items-center justify-center text-[9px] font-bold flex-shrink-0"
                    style={{ background: "rgba(129,140,248,0.15)", border: "1px solid rgba(129,140,248,0.3)", color: "#818cf8" }}
                    aria-hidden="true"
                  >
                    C
                  </div>
                  <span className="text-xs font-semibold tracking-wide" style={{ color: "#818cf8" }}>Claude</span>
                </div>
                <div className="pl-7 flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full dot-1 flex-shrink-0" style={{ background: "#475569" }} />
                  <span className="w-1.5 h-1.5 rounded-full dot-2 flex-shrink-0" style={{ background: "#475569" }} />
                  <span className="w-1.5 h-1.5 rounded-full dot-3 flex-shrink-0" style={{ background: "#475569" }} />
                  {streamingStatus && (
                    <span
                      className="text-xs ml-1 animate-pulse"
                      style={{ color: "#64748b" }}
                    >
                      {streamingStatus}
                    </span>
                  )}
                </div>
              </div>
            )}

            {/* ストリーミング中のツール使用ステータス */}
            {isStreaming && streamingStatus && messages[messages.length - 1]?.role === "assistant" && messages[messages.length - 1]?.isStreaming && (
              <div className="pl-7 mt-1 flex items-center gap-1.5 max-w-3xl mx-auto w-full">
                <span
                  className="text-xs animate-pulse"
                  style={{ color: "#475569" }}
                >
                  {streamingStatus}
                </span>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}
      </section>

      {/* ── 入力エリア ── */}
      <footer
        className="px-4 py-4 flex-shrink-0 sm:px-6"
        style={{
          background: "rgba(7,9,15,0.8)",
          borderTop: "1px solid rgba(255,255,255,0.06)",
          backdropFilter: "blur(12px)",
        }}
      >
        <form onSubmit={handleSubmit} className="max-w-3xl mx-auto">
          {/* 添付ファイルチップ */}
          {attachedFiles.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-2">
              {attachedFiles.map((f) => (
                <div
                  key={f.name}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs"
                  style={{
                    background: "rgba(251,191,36,0.08)",
                    border: "1px solid rgba(251,191,36,0.2)",
                    color: "#fbbf24",
                  }}
                >
                  <span>📎</span>
                  <span className="max-w-[140px] truncate">{f.name}</span>
                  <span style={{ color: "#78716c" }}>({formatBytes(f.size)})</span>
                  <button
                    type="button"
                    onClick={() => removeFile(f.name)}
                    className="ml-0.5 opacity-60 hover:opacity-100 transition-opacity"
                    aria-label={`${f.name} を削除`}
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}

          <div
            className="flex items-end gap-3 rounded-2xl px-4 py-3 transition-all duration-150"
            style={{
              background: "rgba(255,255,255,0.04)",
              border: "1.5px solid rgba(255,255,255,0.08)",
            }}
            onFocusCapture={(e) => {
              e.currentTarget.style.borderColor = "rgba(251,191,36,0.4)";
              e.currentTarget.style.boxShadow = "0 0 0 3px rgba(251,191,36,0.06)";
              e.currentTarget.style.background = "rgba(255,255,255,0.05)";
            }}
            onBlurCapture={(e) => {
              e.currentTarget.style.borderColor = "rgba(255,255,255,0.08)";
              e.currentTarget.style.boxShadow = "none";
              e.currentTarget.style.background = "rgba(255,255,255,0.04)";
            }}
          >
            {/* 添付ボタン */}
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={ACCEPTED_TYPES}
              onChange={handleFileChange}
              className="hidden"
              aria-label="ファイルを添付"
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isStreaming}
              className="flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center transition-all duration-150 disabled:opacity-25"
              style={{ color: "#475569" }}
              onMouseEnter={(e) => { e.currentTarget.style.color = "#fbbf24"; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = "#475569"; }}
              title="ファイルを添付 (.txt .md .csv .docx .pdf)"
              aria-label="ファイルを添付"
            >
              {/* Paperclip icon */}
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
                <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
              </svg>
            </button>

            <label htmlFor="chat-input" className="sr-only">メッセージを入力</label>
            <textarea
              ref={textareaRef}
              id="chat-input"
              value={inputValue}
              onChange={(e) => { setInputValue(e.target.value); adjustHeight(); }}
              onKeyDown={handleKeyDown}
              placeholder={MODE_PLACEHOLDERS[mode]}
              rows={1}
              disabled={isStreaming}
              className="flex-1 resize-none bg-transparent text-sm outline-none min-h-[24px] leading-relaxed disabled:opacity-40"
              style={{ color: "#e2e8f0" }}
              aria-label="チャット入力"
            />
            <button
              type="submit"
              disabled={!canSend}
              className="flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center transition-all duration-150 disabled:opacity-25"
              style={{
                background: canSend
                  ? "linear-gradient(135deg, #f59e0b, #d97706)"
                  : "rgba(255,255,255,0.06)",
                boxShadow: canSend ? "0 2px 12px rgba(245,158,11,0.4)" : "none",
              }}
              aria-label="送信"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="currentColor"
                className="w-4 h-4"
                style={{ color: canSend ? "#0a0f1e" : "#475569" }}
              >
                <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z" />
              </svg>
            </button>
          </div>
          <p className="text-center text-xs mt-2" style={{ color: "#334155" }}>
            Enter で送信 · Shift+Enter で改行 · 📎 でファイル添付
          </p>
        </form>
      </footer>
    </div>
  );
}
