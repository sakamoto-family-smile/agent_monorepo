/**
 * /api/chat のストリーミングプロキシ
 *
 * Next.js の rewrites() はレスポンスをバッファリングするため SSE が機能しない。
 * Route Handler でバックエンドの SSE ストリームをそのまま転送することで解決する。
 * JSON / multipart 両方のリクエストボディを透過的に転送する。
 */
import { type NextRequest, NextResponse } from "next/server";

const BACKEND_URL =
  process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

export async function POST(request: NextRequest) {
  const authHeader = request.headers.get("Authorization") ?? "";
  const contentType = request.headers.get("Content-Type") ?? "application/json";

  // リクエストボディをバイト列として読み取り（JSON / multipart 両対応）
  const rawBody = await request.arrayBuffer();

  let backendResponse: Response;
  try {
    backendResponse = await fetch(`${BACKEND_URL}/api/chat`, {
      method: "POST",
      headers: {
        // Content-Type をそのまま転送（multipart の boundary も保持される）
        "Content-Type": contentType,
        Authorization: authHeader,
      },
      body: rawBody,
    });
  } catch {
    return NextResponse.json(
      { error: "バックエンドに接続できませんでした" },
      { status: 502 }
    );
  }

  if (!backendResponse.ok || !backendResponse.body) {
    return NextResponse.json(
      { error: `バックエンドエラー: ${backendResponse.status}` },
      { status: backendResponse.status }
    );
  }

  // SSE ストリームをそのまま転送（バッファリングしない）
  return new Response(backendResponse.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
