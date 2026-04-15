"use client";

export type AgentMode = "research" | "survey" | "interview" | "review";

interface ModeSelectorProps {
  currentMode: AgentMode;
  onChange: (mode: AgentMode) => void;
  disabled?: boolean;
}

const MODES: { value: AgentMode; label: string; short: string; color: string; bg: string }[] = [
  { value: "research", label: "研究テーマ設計", short: "研究",   color: "#60a5fa", bg: "rgba(96,165,250,0.12)"  },
  { value: "survey",   label: "論文サーベイ",   short: "論文",   color: "#34d399", bg: "rgba(52,211,153,0.12)"  },
  { value: "interview",label: "面接対策",       short: "面接",   color: "#fb923c", bg: "rgba(251,146,60,0.12)"  },
  { value: "review",   label: "計画レビュー",   short: "レビュー",color: "#c084fc", bg: "rgba(192,132,252,0.12)" },
];

export function ModeSelector({ currentMode, onChange, disabled = false }: ModeSelectorProps) {
  return (
    <nav aria-label="モード選択" className="flex gap-1.5 flex-wrap">
      {MODES.map((mode) => {
        const isActive = currentMode === mode.value;
        return (
          <button
            key={mode.value}
            onClick={() => onChange(mode.value)}
            disabled={disabled}
            aria-pressed={isActive}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all duration-150 disabled:opacity-40 disabled:cursor-not-allowed"
            style={{
              background: isActive ? mode.bg : "rgba(255,255,255,0.04)",
              border: `1px solid ${isActive ? mode.color + "50" : "rgba(255,255,255,0.08)"}`,
              color: isActive ? mode.color : "#475569",
              boxShadow: isActive ? `0 0 14px ${mode.color}25` : "none",
            }}
          >
            <span
              className="w-1.5 h-1.5 rounded-full flex-shrink-0"
              style={{ background: mode.color, opacity: isActive ? 1 : 0.5 }}
            />
            <span className="hidden sm:inline">{mode.label}</span>
            <span className="sm:hidden">{mode.short}</span>
          </button>
        );
      })}
    </nav>
  );
}
