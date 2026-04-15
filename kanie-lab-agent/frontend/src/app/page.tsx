"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";

export default function LoginPage() {
  const router = useRouter();
  const { signIn, signUp, loading, error } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSignUp, setIsSignUp] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => { setMounted(true); }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    if (!email || !password) {
      setFormError("メールアドレスとパスワードを入力してください");
      return;
    }
    try {
      if (isSignUp) {
        await signUp(email, password);
      } else {
        await signIn(email, password);
      }
      router.push("/chat");
    } catch (err: unknown) {
      const code = (err as { code?: string })?.code ?? "";
      if (isSignUp) {
        if (code === "auth/email-already-in-use") {
          setFormError("このメールアドレスはすでに登録されています。");
        } else if (code === "auth/weak-password") {
          setFormError("パスワードは6文字以上で入力してください。");
        } else if (code === "auth/invalid-email") {
          setFormError("メールアドレスの形式が正しくありません。");
        } else {
          setFormError(`アカウント作成に失敗しました。(${code || "不明なエラー"})`);
        }
      } else {
        if (
          code === "auth/user-not-found" ||
          code === "auth/wrong-password" ||
          code === "auth/invalid-credential"
        ) {
          setFormError("メールアドレスまたはパスワードが正しくありません。");
        } else if (code === "auth/network-request-failed") {
          setFormError("ネットワークエラーが発生しました。");
        } else {
          setFormError(`ログインに失敗しました。(${code || "不明なエラー"})`);
        }
      }
    }
  };

  if (!mounted) {
    return <div className="min-h-screen w-full" style={{ background: "#0d0d0f" }} />;
  }

  return (
    <div
      className="min-h-screen w-full flex items-center justify-center p-6"
      style={{ background: "#0d0d0f" }}
    >
      <div className="w-full max-w-[360px]">
        {/* ヘッダー */}
        <header className="text-center mb-8">
          <div
            className="inline-flex items-center justify-center w-10 h-10 rounded-xl mb-5 text-sm font-bold"
            style={{
              background: "rgba(129,140,248,0.12)",
              border: "1px solid rgba(129,140,248,0.25)",
              color: "#818cf8",
            }}
          >
            蟹
          </div>
          <h1
            className="text-lg font-semibold tracking-tight mb-1"
            style={{ color: "#f1f5f9" }}
          >
            蟹江研究室
          </h1>
          <p className="text-xs" style={{ color: "#475569" }}>
            大学院入試準備エージェント
          </p>
        </header>

        {/* フォームカード */}
        <div
          className="rounded-xl p-6"
          style={{
            background: "#161618",
            border: "1px solid rgba(255,255,255,0.07)",
          }}
        >
          <p
            className="text-xs font-semibold uppercase tracking-widest mb-5"
            style={{ color: "#334155" }}
          >
            {isSignUp ? "新規登録" : "サインイン"}
          </p>

          <form onSubmit={handleSubmit} className="space-y-3">
            {(formError || error) && (
              <div
                role="alert"
                className="text-xs px-3 py-2.5 rounded-lg"
                style={{
                  background: "rgba(239,68,68,0.08)",
                  border: "1px solid rgba(239,68,68,0.2)",
                  color: "#fca5a5",
                }}
              >
                {formError || error}
              </div>
            )}

            {/* メール */}
            <div className="space-y-1.5">
              <label
                htmlFor="email"
                className="block text-xs font-medium"
                style={{ color: "#64748b" }}
              >
                メールアドレス
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                autoComplete="email"
                required
                className="w-full px-3 py-2.5 rounded-lg text-sm outline-none transition-all duration-150"
                style={{
                  background: "rgba(255,255,255,0.04)",
                  border: "1px solid rgba(255,255,255,0.08)",
                  color: "#f1f5f9",
                }}
                onFocus={(e) => {
                  e.currentTarget.style.borderColor = "rgba(129,140,248,0.5)";
                  e.currentTarget.style.background = "rgba(255,255,255,0.06)";
                }}
                onBlur={(e) => {
                  e.currentTarget.style.borderColor = "rgba(255,255,255,0.08)";
                  e.currentTarget.style.background = "rgba(255,255,255,0.04)";
                }}
              />
            </div>

            {/* パスワード */}
            <div className="space-y-1.5">
              <label
                htmlFor="password"
                className="block text-xs font-medium"
                style={{ color: "#64748b" }}
              >
                パスワード
              </label>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={isSignUp ? "6文字以上" : "••••••••"}
                  autoComplete={isSignUp ? "new-password" : "current-password"}
                  required
                  className="w-full px-3 py-2.5 pr-10 rounded-lg text-sm outline-none transition-all duration-150"
                  style={{
                    background: "rgba(255,255,255,0.04)",
                    border: "1px solid rgba(255,255,255,0.08)",
                    color: "#f1f5f9",
                  }}
                  onFocus={(e) => {
                    e.currentTarget.style.borderColor = "rgba(129,140,248,0.5)";
                    e.currentTarget.style.background = "rgba(255,255,255,0.06)";
                  }}
                  onBlur={(e) => {
                    e.currentTarget.style.borderColor = "rgba(255,255,255,0.08)";
                    e.currentTarget.style.background = "rgba(255,255,255,0.04)";
                  }}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 transition-colors"
                  style={{ color: "#334155" }}
                  onMouseEnter={(e) => { e.currentTarget.style.color = "#64748b"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.color = "#334155"; }}
                  aria-label={showPassword ? "パスワードを隠す" : "パスワードを表示"}
                >
                  {showPassword ? (
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88" />
                    </svg>
                  ) : (
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    </svg>
                  )}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 px-4 rounded-lg text-sm font-semibold transition-all duration-150 disabled:opacity-40 disabled:cursor-not-allowed mt-2"
              style={{
                background: "rgba(129,140,248,0.9)",
                color: "#0d0d0f",
              }}
              onMouseEnter={(e) => { if (!loading) e.currentTarget.style.background = "rgba(129,140,248,1)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(129,140,248,0.9)"; }}
            >
              {loading ? "処理中..." : isSignUp ? "アカウントを作成" : "ログイン"}
            </button>
          </form>

          <div className="mt-4 text-center">
            <button
              onClick={() => { setIsSignUp(!isSignUp); setFormError(null); setShowPassword(false); }}
              className="text-xs transition-colors"
              style={{ color: "#334155" }}
              onMouseEnter={(e) => { e.currentTarget.style.color = "#64748b"; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = "#334155"; }}
            >
              {isSignUp ? "すでにアカウントをお持ちの方" : "アカウントをお持ちでない方"}
            </button>
          </div>
        </div>

        <p className="text-center text-xs mt-6" style={{ color: "#1e293b" }}>
          Powered by Claude
        </p>
      </div>
    </div>
  );
}
