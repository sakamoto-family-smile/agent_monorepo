import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Docker スタンドアロンビルド（Cloud Run 用）
  output: process.env.NODE_ENV === "production" ? "standalone" : undefined,

  // バックエンドAPIへのリバースプロキシ設定
  async rewrites() {
    const backendUrl = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
