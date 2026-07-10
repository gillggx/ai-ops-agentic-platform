/**
 * Mobile (6吋) design tokens — 2026-07-11 handoff「Operation Platform 手機版」.
 * 米色底 / IBM Plex Mono 數字 / HIGH 磚紅・MED 琥珀・AI 洋紅。
 * 主題色沿用桌機的 7 個 CSS 變數；語意色（管制紅/成功綠）固定不隨主題。
 */
export const M = {
  bg: "var(--ws, #F3F1EA)",
  card: "#ffffff",
  line: "#e7e4da",
  ink: "#1a1d29",
  sub: "#5b6070",
  faint: "#8b90a7",
  high: "#A8352A",
  highBg: "#F6E2DF",
  med: "#B07A1E",
  medBg: "#F6ECD9",
  low: "#5b6070",
  lowBg: "#EEEFF2",
  ai: "#A62360",
  aiBg: "#FAEDF3",
  ok: "#0f9d6a",
  okBg: "#e7f7ef",
  crit: "#e5484d",
  mono: "'IBM Plex Mono', ui-monospace, Menlo, monospace",
  sans: "'Noto Sans TC', system-ui, sans-serif",
  shadow: "0 4px 12px -8px rgba(20,23,60,.18)",
} as const;

export function sevTone(sev: string | null | undefined): { fg: string; bg: string; label: string } {
  const s = (sev ?? "").toLowerCase();
  if (s === "critical" || s === "high" || s === "crit") return { fg: M.high, bg: M.highBg, label: "HIGH" };
  if (s === "med" || s === "medium" || s === "warn") return { fg: M.med, bg: M.medBg, label: "MED" };
  return { fg: M.low, bg: M.lowBg, label: "LOW" };
}

export function ageLabel(iso: string | null | undefined): string {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 3600) return `${Math.max(1, Math.floor(s / 60))}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export const cardStyle: React.CSSProperties = {
  background: M.card,
  border: `1px solid ${M.line}`,
  borderRadius: 14,
  boxShadow: M.shadow,
};
