"use client";

import { useState, useEffect } from "react";
import {
  onAuthStateChanged,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signOut as firebaseSignOut,
  type User,
} from "firebase/auth";
import { auth } from "@/lib/firebase";

interface UseAuthReturn {
  user: User | null;
  loading: boolean;
  error: string | null;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

/**
 * Firebase認証を管理するカスタムフック
 */
export function useAuth(): UseAuthReturn {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 認証状態の監視
  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (currentUser) => {
      setUser(currentUser);
      setLoading(false);
    });

    // クリーンアップ: コンポーネントのアンマウント時にリスナーを解除
    return () => unsubscribe();
  }, []);

  /**
   * メールアドレスとパスワードでログイン
   */
  const signIn = async (email: string, password: string): Promise<void> => {
    setError(null);
    setLoading(true);
    try {
      await signInWithEmailAndPassword(auth, email, password);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "ログインに失敗しました";
      setError(message);
      throw err;
    } finally {
      setLoading(false);
    }
  };

  /**
   * 新規アカウント作成
   */
  const signUp = async (email: string, password: string): Promise<void> => {
    setError(null);
    setLoading(true);
    try {
      await createUserWithEmailAndPassword(auth, email, password);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "アカウント作成に失敗しました";
      setError(message);
      throw err;
    } finally {
      setLoading(false);
    }
  };

  /**
   * ログアウト
   */
  const signOut = async (): Promise<void> => {
    setError(null);
    try {
      await firebaseSignOut(auth);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "ログアウトに失敗しました";
      setError(message);
      throw err;
    }
  };

  return { user, loading, error, signIn, signUp, signOut };
}
