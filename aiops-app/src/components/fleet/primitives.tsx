"use client";

/**
 * Reusable SVG primitives for the fleet overview. Ported from the
 * Claude-generated handoff prototype's `charts.jsx` (no chart lib —
 * plain SVG, ≤200-point compatible).
 */

export type Severity = "crit" | "warn" | "ok" | "healthy" | "info" | "neutral";

export const SEV_COLOR: Record<string, string> = {
  crit: "#b8392f",
  warn: "#b87a1f",
  ok: "#2f8a5b",
  healthy: "#2f8a5b",
  info: "#3a64b8",
  neutral: "#76767a",
};

// ── Spark line ─────────────────────────────────────────────────

export function Spark({ values, w = 80, h = 24, color = "#76767a", showArea = true }: {
  values: number[]; w?: number; h?: number; color?: string; showArea?: boolean;
}) {
  if (!values || !values.length) return null;
  const max = Math.max(...values, 0);
  const min = Math.min(...values, 0);
  const range = max - min || 1;
  const step = w / Math.max(1, values.length - 1);
  const pts = values.map((v, i) => [i * step, h - ((v - min) / range) * h] as const);
  const path = pts.map((p, i) => (i === 0 ? "M" : "L") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const area = path + ` L ${w} ${h} L 0 ${h} Z`;
  return (
    <svg width={w} height={h} style={{ display: "block", overflow: "visible" }}>
      {showArea && <path d={area} fill={color} opacity={0.12} />}
      <path d={path} fill="none" stroke={color} strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ── Status dot ─────────────────────────────────────────────────

export function StatusDot({ status, size = 8 }: { status: string; size?: number }) {
  return (
    <span
      className={"status-dot status-dot--" + status}
      style={{ width: size, height: size, background: SEV_COLOR[status] ?? SEV_COLOR.neutral, display: "inline-block", borderRadius: "50%", flexShrink: 0 }}
    />
  );
}

// ── Pill ───────────────────────────────────────────────────────

export function Pill({ kind = "neutral", children }: { kind?: Severity; children: React.ReactNode }) {
  return (
    <span className={`pill pill-${kind}`}>{children}</span>
  );
}

// ── Hour strip — 24-bucket OOC heat strip ──────────────────────

function heatColor(v: number, max = 35): string {
  // 0-bucket gets a faint visible gray (was #fafaf9 = page bg, which made
  // empty hours render as invisible gaps and the whole strip looked skewed
  // when 24h activity was spotty).
  if (v <= 0) return "#ededea";
  const t = Math.min(1, v / max);
  if (t < 0.33) {
    const k = t / 0.33;
    return `rgb(${244}, ${Math.round(244 - 32 * k)}, ${Math.round(242 - 110 * k)})`;
  }
  if (t < 0.66) {
    const k = (t - 0.33) / 0.33;
    return `rgb(${Math.round(244 - 30 * k)}, ${Math.round(212 - 80 * k)}, ${Math.round(132 - 70 * k)})`;
  }
  const k = (t - 0.66) / 0.34;
  return `rgb(${214}, ${Math.round(132 - 40 * k)}, ${Math.round(62 - 30 * k)})`;
}

export function HourStrip({ values, w = 220, h = 14 }: { values: number[]; w?: number; h?: number }) {
  if (!values || !values.length) return null;
  const max = Math.max(...values, 1);
  const cellW = w / values.length;
  return (
    <svg width={w} height={h} style={{ display: "block" }}>
      {values.map((v, i) => (
        <rect
          key={i}
          x={i * cellW}
          y={0}
          width={Math.max(1, cellW - 0.5)}
          height={h}
          fill={heatColor(v, max * 1.2)}
        />
      ))}
    </svg>
  );
}

// ── Trend arrow ────────────────────────────────────────────────

export function TrendArrow({ dir }: { dir: "up" | "down" | "flat" }) {
  if (dir === "down") return <span className="mono" style={{ color: SEV_COLOR.crit }}>▾ worsening</span>;
  if (dir === "up") return <span className="mono" style={{ color: SEV_COLOR.ok }}>▴ improving</span>;
  return <span className="mono" style={{ color: "#76767a" }}>— stable</span>;
}
