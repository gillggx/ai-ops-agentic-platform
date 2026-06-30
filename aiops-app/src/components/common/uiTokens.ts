/**
 * Shared UI design tokens — single source of truth for the "1a · Clarity"
 * visual language (indigo accent, card surfaces, mono data). Used by the
 * System MCP admin screens and the shared DataResultView; safe to reuse
 * anywhere. Fonts use system fallbacks (no Google Fonts).
 *
 * Keep this presentational only: colours, spacing, and small style builders.
 * No state, no data logic.
 */
import type { CSSProperties } from "react";

export const T = {
  // surfaces
  page: "#e9edf3", card: "#fff", subtle: "#fafbfd", subtle2: "#fbfcfe", panel: "#f8fafc",
  // borders
  bd: "#e2e8f0", bdIn: "#e8edf3", hair: "#eef2f6",
  // text
  text: "#0f172a", labelC: "#334155", muted: "#64748b", faint: "#94a3b8", faint2: "#cbd5e1",
  // accent (indigo)
  accent: "#4f46e5", accentBg: "#eef2ff", accentSoft: "#c7d2fe", accentMid: "#6366f1", accentFaint: "#818cf8",
  // status
  okT: "#15803d", okBg: "#dcfce7", dot: "#22c55e",
  danger: "#e11d48", dangerBg: "#ffe4e6", dangerBd: "#fecdd3", oocT: "#b91c1c", oocBg: "#fee2e2",
  warnBg: "#fffbeb", warnBd: "#fde68a", warnT: "#92400e",
  // json syntax
  jKey: "#334155", jStr: "#15803d", jNum: "#1d4ed8", jBool: "#7c3aed", jNull: "#94a3b8",
  typeT: "#0369a1", typeBg: "#e0f2fe",
  // fonts (system fallbacks)
  mono: 'ui-monospace, "JetBrains Mono", SFMono-Regular, Menlo, monospace',
  sans: 'system-ui, "IBM Plex Sans", -apple-system, "Segoe UI", sans-serif',
} as const;

export const card: CSSProperties = {
  background: T.card, border: `1px solid ${T.bdIn}`, borderRadius: 14, padding: 18,
};

export const secTitle: CSSProperties = {
  fontSize: 12, fontWeight: 700, letterSpacing: "0.08em",
  textTransform: "uppercase", color: T.accent,
};

export const secHint: CSSProperties = {
  fontFamily: T.mono, fontSize: 11.5, color: T.faint, fontWeight: 500,
};

export const flabel: CSSProperties = {
  fontSize: 12.5, fontWeight: 600, color: T.labelC, marginBottom: 5, display: "block",
};

export const inp: CSSProperties = {
  width: "100%", padding: "9px 12px", fontSize: 13.5, border: `1px solid ${T.bd}`,
  borderRadius: 9, background: "#fff", outline: "none", fontFamily: T.mono,
  color: T.text, boxSizing: "border-box",
};

export function btn(variant: "primary" | "ghost" | "danger" | "soft" | "dim"): CSSProperties {
  const base: CSSProperties = {
    borderRadius: 9, padding: "9px 18px", fontSize: 13.5, fontWeight: 600,
    cursor: "pointer", border: "1px solid transparent", whiteSpace: "nowrap",
  };
  if (variant === "primary") return { ...base, background: T.accent, color: "#fff", boxShadow: "0 1px 2px rgba(79,70,229,.3)" };
  if (variant === "ghost")   return { ...base, background: "#fff", color: T.muted, border: `1px solid ${T.bd}` };
  if (variant === "danger")  return { ...base, background: "#fff", color: T.danger, border: `1px solid ${T.dangerBd}` };
  if (variant === "soft")    return { ...base, background: T.accentBg, color: T.accent, border: "none", padding: "5px 11px", fontSize: 12 };
  return { ...base, background: "transparent", color: T.muted, border: `1px solid ${T.bd}`, padding: "6px 12px", fontSize: 12 };
}

export function pill(tone: "sys" | "vis" | "ok" | "warn"): CSSProperties {
  const base: CSSProperties = {
    fontSize: 11.5, fontWeight: 700, borderRadius: 20, padding: "2px 10px",
    display: "inline-flex", alignItems: "center", gap: 5,
  };
  if (tone === "sys")  return { ...base, color: T.accent, background: T.accentBg };
  if (tone === "ok")   return { ...base, color: T.okT, background: T.okBg };
  if (tone === "warn") return { ...base, color: T.warnT, background: T.warnBg };
  return { ...base, color: T.muted, background: "#f1f5f9" };
}
