import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        navy: {
          950: "#05080f",
          900: "#0a0f1e",
          800: "#0f172a",
          700: "#1a2440",
          600: "#243058",
          500: "#2e3d70",
        },
        gold: {
          300: "#fde68a",
          400: "#fbbf24",
          500: "#f59e0b",
          600: "#d97706",
        },
        ink: {
          50:  "#f8fafc",
          100: "#f1f5f9",
          200: "#e2e8f0",
          300: "#cbd5e1",
          400: "#94a3b8",
          500: "#64748b",
          600: "#475569",
          700: "#334155",
          800: "#1e293b",
          900: "#0f172a",
        },
      },
      fontFamily: {
        sans: ["var(--font-inter)", "Hiragino Kaku Gothic ProN", "Yu Gothic", "sans-serif"],
        mono: ["var(--font-mono)", "monospace"],
      },
      backgroundImage: {
        "navy-radial":
          "radial-gradient(ellipse 80% 60% at 20% 50%, oklch(30% 0.08 250 / 0.6), transparent)",
        "gold-glow":
          "radial-gradient(ellipse 40% 40% at 50% 0%, oklch(80% 0.18 85 / 0.15), transparent)",
      },
      boxShadow: {
        "glass": "0 4px 24px 0 rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.08)",
        "message": "0 1px 4px 0 rgba(0,0,0,0.08)",
        "input": "0 0 0 3px rgba(251,191,36,0.15)",
      },
      typography: {
        DEFAULT: {
          css: {
            maxWidth: "none",
            color: "#1e293b",
            a: { color: "#d97706", "&:hover": { color: "#f59e0b" } },
          },
        },
      },
    },
  },
  plugins: [require("@tailwindcss/typography")],
};

export default config;
