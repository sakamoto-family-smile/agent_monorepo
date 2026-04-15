"use client";

import { useState, useCallback } from "react";
import { type Message } from "@/components/MessageBubble";
import { type AgentMode } from "@/components/ModeSelector";
import { getSessions, getSessionMessages, type Session } from "@/lib/api";
import { streamChat } from "@/lib/sse";
import { getChatToken } from "@/lib/api";
import { v4 as uuidv4 } from "uuid";

interface UseChatReturn {
  sessions: Session[];
  currentSessionId: string | null;
  messages: Message[];
  mode: AgentMode;
  isStreaming: boolean;
  streamingStatus: string;
  loadSessions: () => Promise<void>;
  selectSession: (sessionId: string) => Promise<void>;
  startNewSession: () => void;
  setMode: (mode: AgentMode) => void;
  sendMessage: (message: string, files?: File[]) => Promise<void>;
}

/**
 * チャット機能全体を管理するカスタムフック
 */
export function useChat(): UseChatReturn {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [mode, setMode] = useState<AgentMode>("research");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingStatus, setStreamingStatus] = useState("");

  /**
   * セッション一覧を取得する
   */
  const loadSessions = useCallback(async () => {
    try {
      const fetchedSessions = await getSessions();
      setSessions(fetchedSessions);
    } catch (err) {
      console.error("セッション取得エラー:", err);
    }
  }, []);

  /**
   * セッションを選択してメッセージを読み込む
   */
  const selectSession = useCallback(async (sessionId: string) => {
    setCurrentSessionId(sessionId);
    try {
      const apiMessages = await getSessionMessages(sessionId);
      const formattedMessages: Message[] = apiMessages.map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        timestamp: new Date(m.timestamp as string),
      }));
      setMessages(formattedMessages);
    } catch (err) {
      console.error("メッセージ取得エラー:", err);
    }
  }, []);

  /**
   * 新しいセッションを開始する
   */
  const startNewSession = useCallback(() => {
    setCurrentSessionId(null);
    setMessages([]);
  }, []);

  /**
   * メッセージを送信してSSEストリームを受け取る
   */
  const sendMessage = useCallback(
    async (message: string, files?: File[]) => {
      if (isStreaming || (!message.trim() && (!files || files.length === 0))) return;

      setIsStreaming(true);
      setStreamingStatus("🤔 考え中...");

      // ユーザーメッセージを即座に表示
      const userMessage: Message = {
        id: uuidv4(),
        role: "user",
        content: message,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userMessage]);

      // アシスタントのメッセージ（ストリーミング中）を準備
      const assistantMessageId = uuidv4();
      const streamingMessage: Message = {
        id: assistantMessageId,
        role: "assistant",
        content: "",
        isStreaming: true,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, streamingMessage]);

      try {
        const token = await getChatToken();
        let accumulatedContent = "";

        await streamChat({
          message,
          files,
          sessionId: currentSessionId,
          mode,
          token,
          onStatus: (statusMessage) => {
            setStreamingStatus(statusMessage);
          },
          onText: (text) => {
            // テキストが来たらステータスをクリアして本文を表示
            setStreamingStatus("");
            accumulatedContent += text;
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMessageId
                  ? { ...m, content: accumulatedContent, isStreaming: true }
                  : m
              )
            );
          },
          onDone: (newSessionId) => {
            // ストリーミング完了
            setStreamingStatus("");
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMessageId
                  ? { ...m, isStreaming: false }
                  : m
              )
            );
            setCurrentSessionId(newSessionId);
            setIsStreaming(false);
            // セッション一覧を更新
            loadSessions();
          },
          onError: (errorMessage) => {
            // エラー時はエラーメッセージを表示
            setStreamingStatus("");
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMessageId
                  ? {
                      ...m,
                      content: `エラーが発生しました: ${errorMessage}`,
                      isStreaming: false,
                    }
                  : m
              )
            );
            setIsStreaming(false);
          },
        });
      } catch (err) {
        // 予期しないエラー
        const errorText =
          err instanceof Error ? err.message : "予期しないエラーが発生しました";
        setStreamingStatus("");
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMessageId
              ? { ...m, content: `エラー: ${errorText}`, isStreaming: false }
              : m
          )
        );
        setIsStreaming(false);
      }
    },
    [isStreaming, currentSessionId, mode, loadSessions] // eslint-disable-line react-hooks/exhaustive-deps
  );

  return {
    sessions,
    currentSessionId,
    messages,
    mode,
    isStreaming,
    streamingStatus,
    loadSessions,
    selectSession,
    startNewSession,
    setMode,
    sendMessage,
  };
}
