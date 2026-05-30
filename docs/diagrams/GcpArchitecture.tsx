"use client";

import { useState } from "react";

/**
 * GcpArchitecture
 * --------------------------------------------------------------------------
 * 追加依存ゼロの GCP 構成図コンポーネント（純粋 SVG + JSX）。
 * React / Next.js のどこにでもそのまま配置できます。
 *
 * デザイン方針（.claude/rules/ecc/web より）:
 *  - 色/間隔/角丸はデザイントークン（TOKENS）に集約し、ハードコードを避ける
 *  - アニメーションは transform / opacity / filter のみ（コンポジタ層）
 *  - hover / focus に「設計された」状態を持たせる
 *  - <svg role="img"> + <title>/<desc> でセマンティクスとアクセシビリティを確保
 */

// ── Design tokens ─────────────────────────────────────────────────────────
const TOKENS = {
  bg: "#0b1220",
  grid: "rgba(148, 163, 184, 0.08)",
  edge: "#64748b",
  edgeActive: "#e2e8f0",
  text: "#e2e8f0",
  textMuted: "#94a3b8",
  vpc: "rgba(66, 133, 244, 0.06)",
  vpcStroke: "rgba(66, 133, 244, 0.35)",
  radius: 14,
  font: "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif",
} as const;

// GCP プロダクトのカテゴリ別カラー（意味づけして使用）
const CATEGORY = {
  network: { fill: "#1f3a8a", stroke: "#4285F4", glow: "rgba(66,133,244,0.45)" },
  compute: { fill: "#0f3d2e", stroke: "#34A853", glow: "rgba(52,168,83,0.40)" },
  data: { fill: "#3b2a06", stroke: "#FBBC04", glow: "rgba(251,188,4,0.40)" },
  ai: { fill: "#3a1620", stroke: "#EA4335", glow: "rgba(234,67,53,0.42)" },
  ops: { fill: "#1f2937", stroke: "#94a3b8", glow: "rgba(148,163,184,0.35)" },
} as const;

type Category = keyof typeof CATEGORY;

type NodeDef = {
  id: string;
  label: string;
  sub: string;
  icon: string;
  x: number;
  y: number;
  w?: number;
  h?: number;
  cat: Category;
};

type EdgeDef = {
  from: string;
  to: string;
  label?: string;
  dashed?: boolean;
};

const NODE_W = 196;
const NODE_H = 64;

// ── Architecture data ─────────────────────────────────────────────────────
const NODES: NodeDef[] = [
  { id: "users", label: "Users", sub: "Web / Mobile", icon: "👥", x: 522, y: 24, cat: "ops" },
  { id: "lb", label: "Cloud Load Balancing", sub: "Global HTTPS LB", icon: "🌐", x: 522, y: 132, cat: "network" },

  { id: "fe", label: "Cloud Run — Frontend", sub: "Next.js 15", icon: "🖥️", x: 300, y: 258, cat: "compute" },
  { id: "api", label: "Cloud Run — Agent API", sub: "FastAPI / LLM", icon: "⚙️", x: 744, y: 258, cat: "compute" },
  { id: "vertex", label: "Vertex AI", sub: "Gemini models", icon: "✨", x: 988, y: 258, cat: "ai" },

  { id: "pubsub", label: "Pub/Sub", sub: "Async jobs", icon: "📨", x: 744, y: 372, cat: "data" },
  { id: "fn", label: "Cloud Functions", sub: "Worker", icon: "λ", x: 988, y: 372, cat: "compute" },

  { id: "firestore", label: "Firestore", sub: "Sessions / chat", icon: "🔥", x: 300, y: 488, cat: "data" },
  { id: "sql", label: "Cloud SQL", sub: "PostgreSQL", icon: "🗄️", x: 522, y: 488, cat: "data" },
  { id: "gcs", label: "Cloud Storage", sub: "Artifacts / files", icon: "🪣", x: 744, y: 488, cat: "data" },

  // ops / security column (left)
  { id: "secret", label: "Secret Manager", sub: "Keys / tokens", icon: "🔐", x: 48, y: 258, w: 172, cat: "ops" },
  { id: "iam", label: "IAM", sub: "Identities / roles", icon: "🛡️", x: 48, y: 350, w: 172, cat: "ops" },
  { id: "obs", label: "Cloud Logging", sub: "Logs / Monitoring", icon: "📊", x: 48, y: 442, w: 172, cat: "ops" },

  // CI/CD (bottom)
  { id: "build", label: "Cloud Build", sub: "CI pipeline", icon: "🏗️", x: 300, y: 612, cat: "ops" },
  { id: "ar", label: "Artifact Registry", sub: "Container images", icon: "📦", x: 522, y: 612, cat: "ops" },
];

const EDGES: EdgeDef[] = [
  { from: "users", to: "lb", label: "HTTPS" },
  { from: "lb", to: "fe" },
  { from: "lb", to: "api" },
  { from: "fe", to: "api", label: "REST / SSE" },
  { from: "api", to: "vertex", label: "inference" },
  { from: "api", to: "firestore" },
  { from: "api", to: "sql" },
  { from: "api", to: "gcs" },
  { from: "api", to: "pubsub", label: "publish" },
  { from: "pubsub", to: "fn" },
  { from: "fn", to: "gcs", dashed: true },
  { from: "fn", to: "vertex", dashed: true },
  { from: "build", to: "ar" },
  { from: "ar", to: "fe", label: "deploy", dashed: true },
  { from: "ar", to: "api", label: "deploy", dashed: true },
];

const NODE_MAP = new Map(NODES.map((n) => [n.id, n]));

function center(n: NodeDef) {
  return { cx: n.x + (n.w ?? NODE_W) / 2, cy: n.y + (n.h ?? NODE_H) / 2 };
}

/** 2 ノード間の接続点を、矩形の縁にスナップして求める */
function anchor(from: NodeDef, to: NodeDef) {
  const a = center(from);
  const b = center(to);
  const fw = (from.w ?? NODE_W) / 2;
  const fh = (from.h ?? NODE_H) / 2;
  const tw = (to.w ?? NODE_W) / 2;
  const th = (to.h ?? NODE_H) / 2;

  const edgePoint = (c: { cx: number; cy: number }, hw: number, hh: number, tx: number, ty: number) => {
    const dx = tx - c.cx;
    const dy = ty - c.cy;
    if (dx === 0 && dy === 0) return { x: c.cx, y: c.cy };
    const scale = 1 / Math.max(Math.abs(dx) / hw, Math.abs(dy) / hh);
    return { x: c.cx + dx * scale, y: c.cy + dy * scale };
  };

  const p1 = edgePoint(a, fw, fh, b.cx, b.cy);
  const p2 = edgePoint(b, tw, th, a.cx, a.cy);
  return { p1, p2 };
}

function GcpNode({
  node,
  active,
  dimmed,
  onHover,
}: {
  node: NodeDef;
  active: boolean;
  dimmed: boolean;
  onHover: (id: string | null) => void;
}) {
  const c = CATEGORY[node.cat];
  const w = node.w ?? NODE_W;
  const h = node.h ?? NODE_H;
  return (
    <g
      transform={`translate(${node.x}, ${node.y})`}
      onMouseEnter={() => onHover(node.id)}
      onMouseLeave={() => onHover(null)}
      tabIndex={0}
      role="listitem"
      aria-label={`${node.label} (${node.sub})`}
      style={{
        cursor: "pointer",
        opacity: dimmed ? 0.35 : 1,
        transition: "opacity 200ms ease, transform 200ms cubic-bezier(0.16,1,0.3,1)",
        transform: active ? "translateY(-3px)" : "translateY(0)",
        outline: "none",
      }}
    >
      <rect
        width={w}
        height={h}
        rx={TOKENS.radius}
        fill={c.fill}
        stroke={c.stroke}
        strokeWidth={active ? 2 : 1.25}
        style={{
          filter: active
            ? `drop-shadow(0 8px 22px ${c.glow})`
            : "drop-shadow(0 2px 6px rgba(0,0,0,0.45))",
          transition: "filter 200ms ease",
        }}
      />
      {/* 左端のカテゴリアクセントバー */}
      <rect width={5} height={h} rx={2.5} fill={c.stroke} />
      <text x={20} y={h / 2 - 4} fontSize={20} dominantBaseline="middle">
        {node.icon}
      </text>
      <text
        x={48}
        y={h / 2 - 9}
        fill={TOKENS.text}
        fontSize={14}
        fontWeight={650}
        fontFamily={TOKENS.font}
      >
        {node.label}
      </text>
      <text x={48} y={h / 2 + 11} fill={TOKENS.textMuted} fontSize={11.5} fontFamily={TOKENS.font}>
        {node.sub}
      </text>
    </g>
  );
}

function GcpEdge({ edge, active, dimmed }: { edge: EdgeDef; active: boolean; dimmed: boolean }) {
  const from = NODE_MAP.get(edge.from);
  const to = NODE_MAP.get(edge.to);
  if (!from || !to) return null;
  const { p1, p2 } = anchor(from, to);
  const mx = (p1.x + p2.x) / 2;
  const my = (p1.y + p2.y) / 2;
  // 軽い曲線で交差を見やすく
  const d = `M ${p1.x} ${p1.y} Q ${mx} ${p1.y} ${mx} ${my} T ${p2.x} ${p2.y}`;
  return (
    <g style={{ opacity: dimmed ? 0.12 : 1, transition: "opacity 200ms ease" }}>
      <path
        d={d}
        fill="none"
        stroke={active ? TOKENS.edgeActive : TOKENS.edge}
        strokeWidth={active ? 2.25 : 1.5}
        strokeDasharray={edge.dashed ? "6 6" : undefined}
        markerEnd={active ? "url(#arrow-active)" : "url(#arrow)"}
        style={{ transition: "stroke 200ms ease, stroke-width 200ms ease" }}
      />
      {edge.label && (
        <text
          x={mx}
          y={my - 6}
          fill={active ? TOKENS.text : TOKENS.textMuted}
          fontSize={11}
          fontFamily={TOKENS.font}
          textAnchor="middle"
          style={{ paintOrder: "stroke", stroke: TOKENS.bg, strokeWidth: 4 }}
        >
          {edge.label}
        </text>
      )}
    </g>
  );
}

export default function GcpArchitecture() {
  const [hover, setHover] = useState<string | null>(null);

  // hover 中ノードに接続するエッジ / ノードだけを強調
  const connected = new Set<string>();
  if (hover) {
    connected.add(hover);
    for (const e of EDGES) {
      if (e.from === hover) connected.add(e.to);
      if (e.to === hover) connected.add(e.from);
    }
  }

  return (
    <figure style={{ margin: 0 }}>
      <svg
        viewBox="0 0 1240 712"
        width="100%"
        role="img"
        aria-labelledby="gcp-arch-title gcp-arch-desc"
        style={{ background: TOKENS.bg, borderRadius: 20, fontFamily: TOKENS.font, display: "block" }}
      >
        <title id="gcp-arch-title">GCP 上のエージェントサービス構成図</title>
        <desc id="gcp-arch-desc">
          Cloud Load Balancing 経由で Cloud Run 上のフロントエンドと Agent API を公開し、Vertex
          AI、Firestore、Cloud SQL、Cloud Storage、Pub/Sub、Cloud Functions と連携する構成。
        </desc>

        <defs>
          <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse">
            <path d="M 32 0 L 0 0 0 32" fill="none" stroke={TOKENS.grid} strokeWidth="1" />
          </pattern>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill={TOKENS.edge} />
          </marker>
          <marker id="arrow-active" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7.5" markerHeight="7.5" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill={TOKENS.edgeActive} />
          </marker>
        </defs>

        <rect width="1240" height="712" fill="url(#grid)" />

        {/* VPC 境界 */}
        <g>
          <rect
            x={252}
            y={210}
            width={764}
            height={342}
            rx={20}
            fill={TOKENS.vpc}
            stroke={TOKENS.vpcStroke}
            strokeWidth={1.5}
            strokeDasharray="3 6"
          />
          <text x={272} y={236} fill={TOKENS.vpcStroke} fontSize={12.5} fontWeight={700} letterSpacing={1}>
            VPC — asia-northeast1
          </text>
        </g>

        {/* edges first (背面) */}
        <g aria-hidden="true">
          {EDGES.map((e, i) => (
            <GcpEdge
              key={i}
              edge={e}
              active={!!hover && (e.from === hover || e.to === hover)}
              dimmed={!!hover && e.from !== hover && e.to !== hover}
            />
          ))}
        </g>

        {/* nodes */}
        <g role="list" aria-label="GCP services">
          {NODES.map((n) => (
            <GcpNode
              key={n.id}
              node={n}
              active={hover === n.id}
              dimmed={!!hover && !connected.has(n.id)}
              onHover={setHover}
            />
          ))}
        </g>
      </svg>

      <figcaption
        style={{
          color: TOKENS.textMuted,
          fontFamily: TOKENS.font,
          fontSize: 13,
          marginTop: 10,
          display: "flex",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        {(
          [
            ["network", "Network"],
            ["compute", "Compute"],
            ["data", "Data"],
            ["ai", "AI"],
            ["ops", "Ops / Security"],
          ] as [Category, string][]
        ).map(([cat, label]) => (
          <span key={cat} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span
              style={{
                width: 12,
                height: 12,
                borderRadius: 4,
                background: CATEGORY[cat].fill,
                border: `1.5px solid ${CATEGORY[cat].stroke}`,
                display: "inline-block",
              }}
            />
            {label}
          </span>
        ))}
        <span style={{ marginLeft: "auto", opacity: 0.8 }}>※ ノードに hover で関連線をハイライト</span>
      </figcaption>
    </figure>
  );
}
