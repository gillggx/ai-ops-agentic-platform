"use client";

import { FocusRef, KIND_COLOR } from "./lib/types";

interface Props {
  focus:        FocusRef | null;
  onClearFocus: () => void;
  query:        string;
  onSearch:     (q: string) => void;
  runCount:     number;
  truncated:    boolean;
  fullscreen:   boolean;
  onToggleFullscreen: () => void;
  onToggleTweaks:     () => void;
}

export default function TopBar({
  focus, onClearFocus, query, onSearch,
  runCount, truncated, fullscreen, onToggleFullscreen, onToggleTweaks,
}: Props) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 14,
      padding: "8px 14px", borderBottom: "1px solid #ececec",
      background: "#fff", fontSize: 11, letterSpacing: "0.04em",
      flex: "0 0 auto",
    }}>
      <div style={{ fontWeight: 600, color: "#111", letterSpacing: "0.08em", fontSize: 11 }}>
        TOPOLOGY · TRACE
      </div>
      <div style={{ width: 1, height: 14, background: "#e5e5e5" }} />

      {/* Search */}
      <div style={{ flex: 1, display: "flex", justifyContent: "center", minWidth: 200 }}>
        <input
          value={query}
          onChange={(e) => onSearch(e.target.value)}
          placeholder="Trace any object…"
          style={{
            width: 320, padding: "5px 10px", fontSize: 11.5,
            border: "1px solid #e0e0e0", borderRadius: 3,
            background: "#fafafa", outline: "none", fontFamily: "inherit",
            color: "#222",
          }}
        />
      </div>

      {focus ? (
        <button
          onClick={onClearFocus}
          style={{
            border: `1px solid ${KIND_COLOR[focus.kind]}50`,
            background: "#fff",
            padding: "4px 10px", borderRadius: 3, cursor: "pointer",
            fontSize: 10.5, letterSpacing: "0.04em",
            color: KIND_COLOR[focus.kind], fontFamily: "inherit",
            fontWeight: 600,
          }}
        >
          CLEAR · {focus.id}
        </button>
      ) : (
        <span style={{ color: "#aaa", fontSize: 10.5, whiteSpace: "nowrap" }}>
          {runCount} RUNS{truncated ? "+" : ""}
        </span>
      )}

      <button
        onClick={onToggleTweaks}
        title="Tweaks"
        style={{
          border: "1px solid #e0e0e0", background: "#fff",
          width: 28, height: 28, borderRadius: 3, cursor: "pointer",
          color: "#555", fontSize: 14, fontFamily: "inherit",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}
      >
        ⚙
      </button>

      <button
        onClick={onToggleFullscreen}
        title={fullscreen ? "Exit fullscreen (Esc)" : "Fullscreen"}
        style={{
          border: "1px solid #e0e0e0", background: fullscreen ? "#111" : "#fff",
          width: 28, height: 28, borderRadius: 3, cursor: "pointer",
          color: fullscreen ? "#fff" : "#555", fontSize: 13, fontFamily: "inherit",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}
      >
        {fullscreen ? "⛶" : "⤢"}
      </button>
    </div>
  );
}
