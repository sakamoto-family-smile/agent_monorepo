// Shared icon sprite loader.
// Combines the auto-generated official Google Cloud sprite (gcp-*) with the
// hand-drawn extra icons (x-*) used by local/dev diagrams. Both are plain
// <symbol> markup, referenced from diagrams via <use href="#gcp-..."> etc.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const DIAGRAMS_DIR = join(dirname(fileURLToPath(import.meta.url)), "..");

const gcp = readFileSync(join(DIAGRAMS_DIR, "gcp-icon-defs.partial.svg"), "utf8");
const extra = readFileSync(join(DIAGRAMS_DIR, "extra-icons-src.svg"), "utf8")
  .replace(/<!--[\s\S]*?-->/g, "")
  .trim();

/** All icon <symbol>s, ready to drop inside an SVG <defs>. */
export const ICON_DEFS = `${gcp}\n${extra}`;
