// fujisawa-platform — LOCAL / dev architecture spec.
// A library run via make targets; optional extras enable pgvector / vertex /
// pdf. Locally the resolver + in-memory / local Postgres back the KB.
// Source: README §0 (make install-* extras, optional Cloud SQL + pgvector).
export const spec = {
  title: "fujisawa-platform — Local / Dev",
  subtitle: "ライブラリ + ETL CLI · ローカル Postgres / in-memory · 任意で Vertex",
  width: 1140,
  height: 560,
  groups: [
    { label: "Developer machine", x: 232, y: 150, w: 600, h: 360 },
  ],
  nodes: [
    { id: "city", label: "藤沢市 HP / PDF", sub: "crawl 対象", icon: "x-globe", x: 470, y: 28, cat: "external" },

    { id: "cli", label: "ETL CLI / pytest", sub: "make test / run_etl", icon: "x-python", x: 470, y: 190, cat: "local" },
    { id: "resolver", label: "resolver + skills", sub: "表記ゆれ / 出典", icon: "x-python", x: 270, y: 320, cat: "local" },
    { id: "pg", label: "Postgres + pgvector", sub: "任意: docker / 省略時 in-memory", icon: "x-postgres", x: 600, y: 320, cat: "local" },

    { id: "vertex", label: "Vertex AI", sub: "任意: 本番 embedding", icon: "gcp-vertexai", x: 880, y: 190, cat: "ai" },
  ],
  edges: [
    { from: "city", to: "cli", label: "crawl" },
    { from: "cli", to: "resolver" },
    { from: "cli", to: "pg", label: "upsert", dashed: true },
    { from: "cli", to: "vertex", label: "embed (任意)", dashed: true },
  ],
};
