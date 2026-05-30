// Data-driven architecture-diagram renderer (shared by every system diagram).
//
// A diagram is described as a plain spec: { title, width, height, groups,
// nodes, edges }. This module renders that spec to a static SVG string. The
// same spec files are imported by the .tsx components, so JSX and static
// previews never drift.
//
// Coordinates are top-left of each node. Nodes auto-size height; width
// defaults to NODE_W. Edges snap to the rectangle border of each endpoint.
import { ICON_DEFS } from "./icons.mjs";

export const TOKENS = {
  bg: "#0b1220",
  grid: "rgba(148,163,184,0.08)",
  edge: "#64748b",
  text: "#e2e8f0",
  textMuted: "#94a3b8",
  radius: 14,
};

// Category palette (semantic, not decorative). `x` covers non-GCP/local tech.
export const CATEGORY = {
  network: { fill: "#1f3a8a", stroke: "#4285F4" },
  compute: { fill: "#0f3d2e", stroke: "#34A853" },
  data: { fill: "#3b2a06", stroke: "#FBBC04" },
  ai: { fill: "#3a1620", stroke: "#EA4335" },
  ops: { fill: "#1f2937", stroke: "#94a3b8" },
  external: { fill: "#312244", stroke: "#a78bfa" },
  local: { fill: "#0e2a33", stroke: "#22d3ee" },
};

export const NODE_W = 200;
export const NODE_H = 64;

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");

const sizeOf = (n) => ({ w: n.w ?? NODE_W, h: n.h ?? NODE_H });
const centerOf = (n) => {
  const { w, h } = sizeOf(n);
  return { cx: n.x + w / 2, cy: n.y + h / 2 };
};

/** Border-snapped endpoints between two node rectangles. */
function anchor(from, to) {
  const a = centerOf(from);
  const b = centerOf(to);
  const fs = sizeOf(from);
  const ts = sizeOf(to);
  const edgePoint = (c, hw, hh, tx, ty) => {
    const dx = tx - c.cx;
    const dy = ty - c.cy;
    if (!dx && !dy) return { x: c.cx, y: c.cy };
    const scale = 1 / Math.max(Math.abs(dx) / hw, Math.abs(dy) / hh);
    return { x: c.cx + dx * scale, y: c.cy + dy * scale };
  };
  return {
    p1: edgePoint(a, fs.w / 2, fs.h / 2, b.cx, b.cy),
    p2: edgePoint(b, ts.w / 2, ts.h / 2, a.cx, a.cy),
  };
}

function renderEdge(edge, nodeMap) {
  const from = nodeMap.get(edge.from);
  const to = nodeMap.get(edge.to);
  if (!from || !to) return "";
  const { p1, p2 } = anchor(from, to);
  const mx = (p1.x + p2.x) / 2;
  const my = (p1.y + p2.y) / 2;
  const d = `M ${p1.x} ${p1.y} Q ${mx} ${p1.y} ${mx} ${my} T ${p2.x} ${p2.y}`;
  let out = `<path d="${d}" fill="none" stroke="${TOKENS.edge}" stroke-width="1.5"${
    edge.dashed ? ' stroke-dasharray="6 6"' : ""
  } marker-end="url(#arrow)"/>`;
  if (edge.label) {
    out += `<text x="${mx}" y="${my - 6}" fill="${TOKENS.textMuted}" font-size="11" text-anchor="middle" paint-order="stroke" stroke="${TOKENS.bg}" stroke-width="4">${esc(
      edge.label,
    )}</text>`;
  }
  return out;
}

function renderNode(node) {
  const cat = CATEGORY[node.cat] ?? CATEGORY.ops;
  const { w, h } = sizeOf(node);
  const chipY = (h - 34) / 2;
  return (
    `<g transform="translate(${node.x},${node.y})">` +
    `<rect width="${w}" height="${h}" rx="${TOKENS.radius}" fill="${cat.fill}" stroke="${cat.stroke}" stroke-width="1.25"/>` +
    `<rect width="5" height="${h}" rx="2.5" fill="${cat.stroke}"/>` +
    `<rect x="14" y="${chipY}" width="34" height="34" rx="9" fill="#f1f5f9"/>` +
    `<use href="#${node.icon}" x="17" y="${chipY + 3}" width="28" height="28"/>` +
    `<text x="60" y="${h / 2 - 9}" fill="${TOKENS.text}" font-size="13" font-weight="650">${esc(node.label)}</text>` +
    `<text x="60" y="${h / 2 + 11}" fill="${TOKENS.textMuted}" font-size="11.5">${esc(node.sub ?? "")}</text>` +
    `</g>`
  );
}

function renderGroup(group) {
  const stroke = group.stroke ?? "rgba(66,133,244,0.35)";
  const fill = group.fill ?? "rgba(66,133,244,0.06)";
  return (
    `<g>` +
    `<rect x="${group.x}" y="${group.y}" width="${group.w}" height="${group.h}" rx="20" fill="${fill}" stroke="${stroke}" stroke-width="1.5" stroke-dasharray="3 6"/>` +
    `<text x="${group.x + 18}" y="${group.y + 24}" fill="${stroke}" font-size="12.5" font-weight="700" letter-spacing="1">${esc(
      group.label,
    )}</text>` +
    `</g>`
  );
}

/** Render a diagram spec to a complete SVG string. */
export function renderDiagram(spec) {
  const width = spec.width ?? 1240;
  const height = spec.height ?? 720;
  const nodeMap = new Map(spec.nodes.map((n) => [n.id, n]));
  const groups = (spec.groups ?? []).map(renderGroup).join("\n");
  const edges = spec.edges.map((e) => renderEdge(e, nodeMap)).join("");
  const nodes = spec.nodes.map(renderNode).join("\n");
  const titleBar = spec.title
    ? `<text x="32" y="44" fill="${TOKENS.text}" font-size="20" font-weight="750">${esc(spec.title)}</text>` +
      (spec.subtitle
        ? `<text x="32" y="66" fill="${TOKENS.textMuted}" font-size="13">${esc(spec.subtitle)}</text>`
        : "")
    : "";

  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" font-family="Inter, system-ui, 'Noto Sans CJK JP', 'IPAGothic', sans-serif">` +
    `<defs>` +
    `<pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse"><path d="M 32 0 L 0 0 0 32" fill="none" stroke="${TOKENS.grid}" stroke-width="1"/></pattern>` +
    `<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="${TOKENS.edge}"/></marker>` +
    ICON_DEFS +
    `</defs>` +
    `<rect width="${width}" height="${height}" fill="${TOKENS.bg}"/>` +
    `<rect width="${width}" height="${height}" fill="url(#grid)"/>` +
    titleBar +
    groups +
    edges +
    nodes +
    `</svg>`
  );
}
