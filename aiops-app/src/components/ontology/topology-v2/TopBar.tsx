"use client";

import { ViewKind, VIEW_LABEL, KIND_COLOR, FocusRef, Kind } from "./lib/types";

interface Props {
  activeView:    ViewKind;
  onPickView:    (v: ViewKind) => void;
  focus:         FocusRef | null;
  onClearFocus:  () => void;
  query:         string;
  onSearch:      (q: string) => void;
  runCount:      number;
  truncated:     boolean;
  fullscreen:    boolean;
  onToggleFullscreen: () => void;
  onToggleTweaks:     () => void;
}

const VIEWS: ViewKind[] = ["trace", "graph", "tool", "lot", "recipe", "apc", "step", "fdc", "spc"];

export default function TopBar({
  activeView, onPickView, focus, onClearFocus, query, onSearch,
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
        TOPOLOGY
      </div>
      <div style={{ width: 1, height: 14, background: "#e5e5e5" }} />

      {/* View picker: 9 buttons */}
      <div style={{ display: "flex", gap: 2, color: "#666" }}>
        <span style={{ marginRight: 6, color: "#999", alignSelf: "center", fontSize: 10 }}>VIEW</span>
        {VIEWS.map((v) => {
          const active = v === activeView;
          const accent = v === "trace" || v === "graph"
            ? "#111"
            : KIND_COLOR[v as Kind];
          return (
            <button
              key={v}
              onClick={() => onPickView(v)}
              style={{
                border:    "none",
                background: active ? accent : "transparent",
                color:      active ? "#fff" : "#444",
                padding:    "4px 9px",
                borderRadius: 3,
                cursor:     "pointer",
                fontSize:   10.5,
                letterSpacing: "0.06em",
                fontWeight: active ? 600 : 500,
                fontFamily: "inherit",
                textTransform: "uppercase",
              }}
            >
              {VIEW_LABEL[v]}
            </button>
          );
        })}
      </div>

      {/* Search */}
      <div style={{ flex: 1, display: "flex", justifyContent: "center", minWidth: 200 }}>
        <input
          value={query}
          onChange={(e) => onSearch(e.target.value)}
          placeholder="Trace any object…"
          style={{
            width: 260, padding: "5px 10px", fontSize: 11.5,
            border: "1px solid #e0e0e0", borderRadius: 3,
            background: "#fafafa", outline: "none", fontFamily: "inherit",
            color: "#222",
          }}
        />
      </div>

      {/* Right meta */}
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

      {/* Tweaks icon (gear) */}
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

      {/* Fullscreen toggle */}
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
