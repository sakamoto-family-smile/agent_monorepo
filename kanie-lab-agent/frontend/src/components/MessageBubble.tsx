"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp?: Date;
  isStreaming?: boolean;
}

export function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";

  return (
    <article
      className="py-5 message-enter"
      style={{ borderBottom: "1px solid rgba(255,255,255,0.05)" }}
      aria-label={`${isUser ? "あなた" : "アシスタント"}のメッセージ`}
    >
      {/* ロールラベル */}
      <div className="flex items-center gap-2 mb-2">
        <div
          className="w-[18px] h-[18px] rounded-[4px] flex items-center justify-center text-[9px] font-bold flex-shrink-0"
          style={
            isUser
              ? { background: "rgba(251,191,36,0.15)", border: "1px solid rgba(251,191,36,0.3)", color: "#fbbf24" }
              : { background: "rgba(129,140,248,0.15)", border: "1px solid rgba(129,140,248,0.3)", color: "#818cf8" }
          }
          aria-hidden="true"
        >
          {isUser ? "Y" : "C"}
        </div>
        <span
          className="text-xs font-semibold tracking-wide"
          style={{ color: isUser ? "#fbbf24" : "#818cf8" }}
        >
          {isUser ? "You" : "Claude"}
        </span>
      </div>

      {/* コンテンツ */}
      <div className="pl-7 text-sm leading-relaxed" style={{ color: "#cbd5e1" }}>
        {isUser ? (
          <p className="whitespace-pre-wrap" style={{ color: "#e2e8f0" }}>
            {message.content}
          </p>
        ) : (
          <div>
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                h1: ({ children }) => (
                  <h1 style={{ color: "#f1f5f9", fontWeight: 600, fontSize: "1.1em", marginTop: "1.2rem", marginBottom: "0.4rem" }}>{children}</h1>
                ),
                h2: ({ children }) => (
                  <h2 style={{ color: "#f1f5f9", fontWeight: 600, fontSize: "1em", marginTop: "1rem", marginBottom: "0.3rem" }}>{children}</h2>
                ),
                h3: ({ children }) => (
                  <h3 style={{ color: "#e2e8f0", fontWeight: 600, marginTop: "0.8rem", marginBottom: "0.2rem" }}>{children}</h3>
                ),
                p: ({ children }) => (
                  <p style={{ color: "#cbd5e1", lineHeight: 1.75, margin: "0.5rem 0" }}>{children}</p>
                ),
                a: ({ href, children }) => (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: "#818cf8", textDecoration: "none" }}
                    onMouseEnter={(e) => { (e.currentTarget as HTMLAnchorElement).style.textDecoration = "underline"; }}
                    onMouseLeave={(e) => { (e.currentTarget as HTMLAnchorElement).style.textDecoration = "none"; }}
                  >
                    {children}
                  </a>
                ),
                code: ({ children, className }) => {
                  const isBlock = className?.includes("language-");
                  return isBlock ? (
                    <code style={{
                      display: "block",
                      background: "rgba(0,0,0,0.35)",
                      border: "1px solid rgba(255,255,255,0.07)",
                      borderRadius: "6px",
                      padding: "12px 14px",
                      fontSize: "0.8em",
                      color: "#7dd3fc",
                      overflowX: "auto",
                      lineHeight: 1.65,
                      fontFamily: "'SF Mono', 'Fira Code', monospace",
                    }}>{children}</code>
                  ) : (
                    <code style={{
                      background: "rgba(0,0,0,0.3)",
                      border: "1px solid rgba(255,255,255,0.07)",
                      borderRadius: "3px",
                      padding: "1px 5px",
                      fontSize: "0.83em",
                      color: "#7dd3fc",
                      fontFamily: "'SF Mono', 'Fira Code', monospace",
                    }}>{children}</code>
                  );
                },
                pre: ({ children }) => (
                  <pre style={{ margin: "0.6rem 0", background: "transparent", overflow: "visible" }}>{children}</pre>
                ),
                blockquote: ({ children }) => (
                  <blockquote style={{
                    borderLeft: "2px solid rgba(129,140,248,0.4)",
                    paddingLeft: "12px",
                    margin: "0.5rem 0",
                    color: "#94a3b8",
                    fontStyle: "italic",
                  }}>{children}</blockquote>
                ),
                ul: ({ children }) => (
                  <ul style={{ paddingLeft: "1.25rem", margin: "0.4rem 0", color: "#cbd5e1" }}>{children}</ul>
                ),
                ol: ({ children }) => (
                  <ol style={{ paddingLeft: "1.25rem", margin: "0.4rem 0", color: "#cbd5e1" }}>{children}</ol>
                ),
                li: ({ children }) => (
                  <li style={{ marginBottom: "0.2rem", color: "#cbd5e1" }}>{children}</li>
                ),
                strong: ({ children }) => (
                  <strong style={{ color: "#f1f5f9", fontWeight: 600 }}>{children}</strong>
                ),
                table: ({ children }) => (
                  <div style={{ overflowX: "auto", margin: "0.75rem 0" }}>
                    <table style={{ borderCollapse: "collapse", width: "100%", fontSize: "0.85em" }}>{children}</table>
                  </div>
                ),
                th: ({ children }) => (
                  <th style={{
                    background: "rgba(255,255,255,0.04)",
                    border: "1px solid rgba(255,255,255,0.08)",
                    padding: "6px 12px",
                    color: "#e2e8f0",
                    fontWeight: 600,
                    textAlign: "left",
                  }}>{children}</th>
                ),
                td: ({ children }) => (
                  <td style={{
                    border: "1px solid rgba(255,255,255,0.06)",
                    padding: "5px 12px",
                    color: "#cbd5e1",
                  }}>{children}</td>
                ),
                hr: () => (
                  <hr style={{ border: "none", borderTop: "1px solid rgba(255,255,255,0.07)", margin: "0.8rem 0" }} />
                ),
              }}
            >
              {message.content}
            </ReactMarkdown>
            {message.isStreaming && (
              <span className="streaming-cursor" aria-label="入力中" />
            )}
          </div>
        )}
      </div>
    </article>
  );
}
