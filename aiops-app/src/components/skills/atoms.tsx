"use client";

/**
 * Skill UI atoms — copied from prototype's app.jsx + library.jsx so the
 * Library and Playbook pages render visually identical to the design.
 */
import type { CSSProperties, ReactNode, MouseEvent } from "react";

/* ── Icons (SVG, sized for inline use) ─────────────────────────────── */
const I = (size: number) => ({ viewBox: "0 0 16 16", width: size, height: size });

export const Icon = {
  Star:    (p: { color?: string }) => <svg {...I(12)} fill="currentColor" {...p}><path d="M8 1.5l2 4.4 4.8.5-3.6 3.3 1 4.7L8 12.1 3.8 14.4l1-4.7L1.2 6.4 6 5.9 8 1.5z"/></svg>,
  Spark:   (p?: { color?: string }) => <svg {...I(13)} fill="currentColor" {...p}><path d="M8 1.5l1.4 4.1 4.1 1.4-4.1 1.4L8 12.5 6.6 8.4 2.5 7l4.1-1.4L8 1.5z"/></svg>,
  Check:   (p?: object) => <svg {...I(14)} fill="none" {...p}><path d="M3 8.5l3 3 7-7.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  X:       (p?: object) => <svg {...I(14)} fill="none" {...p}><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>,
  Plus:    (p?: object) => <svg {...I(13)} fill="none" {...p}><path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>,
  Search:  (p?: object) => <svg {...I(13)} fill="none" {...p}><circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.4"/><path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg>,
  Arrow:   (p?: object) => <svg {...I(11)} fill="none" {...p}><path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  Filter:  (p?: object) => <svg {...I(13)} fill="none" {...p}><path d="M2 4h12M4 8h8M6 12h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>,
  Clock:   (p?: object) => <svg {...I(11)} fill="none" {...p}><circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.4"/><path d="M8 4.5V8l2.5 1.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg>,
  Bolt:    (p?: object) => <svg {...I(13)} fill="currentColor" {...p}><path d="M9 1L3 9h4l-1 6 6-8H8l1-6z"/></svg>,
  Chevron: (p?: object) => <svg {...I(12)} fill="none" {...p}><path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  Play:    (p?: object) => <svg {...I(11)} fill="currentColor" {...p}><path d="M4 2.5v11l9-5.5z"/></svg>,
  Pencil:  (p?: object) => <svg {...I(12)} fill="none" {...p}><path d="M11 2.5l2.5 2.5L5 13.5H2.5V11L11 2.5z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/></svg>,
  Loop:    (p?: object) => <svg {...I(13)} fill="none" {...p}><path d="M3 8a5 5 0 019-3l1.5-1.5M13 8a5 5 0 01-9 3L2.5 12.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg>,
  MoreH:   (p?: object) => <svg {...I(14)} fill="currentColor" {...p}><circle cx="3.5" cy="8" r="1.3"/><circle cx="8" cy="8" r="1.3"/><circle cx="12.5" cy="8" r="1.3"/></svg>,
  Drag:    (p?: object) => <svg {...I(10)} fill="currentColor" {...p}><circle cx="3" cy="3" r="1"/><circle cx="3" cy="8" r="1"/><circle cx="3" cy="13" r="1"/><circle cx="8" cy="3" r="1"/><circle cx="8" cy="8" r="1"/><circle cx="8" cy="13" r="1"/></svg>,
};

/* ── Badge ─────────────────────────────────────────────────────────── */
export type BadgeKind = "ai" | "pass" | "fail" | "warn" | "muted";
export function Badge({
  kind = "ai",
  icon,
  children,
  dim,
}: {
  kind?: BadgeKind;
  icon?: ReactNode;
  children: ReactNode;
  dim?: boolean;
}) {
  const map: Record<BadgeKind, { color: string; bg: string }> = {
    ai:    { color: "var(--ai)",   bg: "var(--ai-bg)" },
    pass:  { color: "var(--pass)", bg: "var(--pass-bg)" },
    fail:  { color: "var(--fail)", bg: "var(--fail-bg)" },
    warn:  { color: "var(--warn)", bg: "var(--warn-bg)" },
    muted: { color: "var(--ink-3)", bg: "var(--surface-2)" },
  };
  const m = map[kind];
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      padding: "2px 8px", borderRadius: 999,
      background: dim ? "transparent" : m.bg,
      color: m.color,
      fontSize: 11, fontWeight: 500,
      border: dim ? "1px solid var(--line)" : "none",
      whiteSpace: "nowrap",
      lineHeight: 1.6,
    }}>
      {icon}
      {children}
    </span>
  );
}

/* ── Btn ───────────────────────────────────────────────────────────── */
export type BtnKind = "primary" | "secondary" | "ghost" | "danger";
export function Btn({
  kind = "ghost",
  icon,
  children,
  onClick,
  disabled,
  fullWidth,
  type = "button",
}: {
  kind?: BtnKind;
  icon?: ReactNode;
  children: ReactNode;
  onClick?: (e: MouseEvent<HTMLButtonElement>) => void;
  disabled?: boolean;
  fullWidth?: boolean;
  type?: "button" | "submit";
}) {
  const styles: Record<BtnKind, { bg: string; fg: string; border: string }> = {
    primary:   { bg: "var(--accent)", fg: "var(--bg)", border: "var(--accent)" },
    secondary: { bg: "var(--surface)", fg: "var(--ink)", border: "var(--line-strong)" },
    ghost:     { bg: "transparent", fg: "var(--ink-2)", border: "transparent" },
    danger:    { bg: "var(--fail)", fg: "#fff", border: "var(--fail)" },
  };
  const s = styles[kind];
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      style={{
        display: "inline-flex", alignItems: "center", gap: 6,
        padding: "6px 11px", borderRadius: 6,
        background: s.bg, color: s.fg,
        border: `1px solid ${s.border}`,
        fontSize: 12.5, fontWeight: 500,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
        width: fullWidth ? "100%" : "auto",
        justifyContent: fullWidth ? "center" : "flex-start",
        transition: "background 120ms, border-color 120ms",
      }}
    >
      {icon}{children}
    </button>
  );
}

/* ── Stat (Library Hero) ──────────────────────────────────────────── */
export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div>
      <div className="mono" style={{ fontSize: 9.5, letterSpacing: "0.08em", color: "var(--ink-3)", marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 600, color: "var(--ink)", letterSpacing: "-0.01em" }}>{value}</div>
      {sub && <div style={{ fontSize: 11.5, color: "var(--ink-3)", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

/* ── Stage taxonomy ─────────────────────────────────────────────────── */
export const STAGES: Record<"patrol" | "diagnose", { label: string; dot: string; desc: string }> = {
  patrol:   { label: "Patrol",   dot: "var(--ai)",   desc: "Continuously watch process health" },
  diagnose: { label: "Diagnose", dot: "var(--warn)", desc: "Pinpoint root cause when triggered" },
};

export function StagePill({ stage, dim }: { stage: "patrol" | "diagnose"; dim?: boolean }) {
  const s = STAGES[stage];
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      padding: "2px 9px", borderRadius: 999,
      fontSize: 11, fontWeight: 500,
      background: dim ? "transparent" : "var(--surface-2)",
      color: "var(--ink-2)",
      border: "1px solid var(--line)",
    }}>
      <span style={{ width: 5, height: 5, borderRadius: 999, background: s.dot }}/>
      {s.label}
    </span>
  );
}

export function StatusDot({ status }: { status: string }) {
  const map: Record<string, { color: string; label: string }> = {
    stable: { color: "var(--pass)", label: "stable" },
    draft:  { color: "var(--warn)", label: "draft" },
  };
  const m = map[status] || map.draft;
  return (
    <span className="mono" style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      fontSize: 10.5, color: "var(--ink-3)", letterSpacing: "0.04em",
    }}>
      <span style={{ width: 6, height: 6, borderRadius: 999, background: m.color }}/>
      {m.label}
    </span>
  );
}

export function TriggerChip({ kind, label }: { kind: "system" | "user" | "schedule"; label: string }) {
  const k = {
    system:   { color: "var(--fail)", icon: <Icon.Bolt/>, prefix: "EVENT" },
    schedule: { color: "var(--pass)", icon: <Icon.Clock/>, prefix: "CRON" },
    user:     { color: "var(--ai)",   icon: <Icon.Spark/>, prefix: "CUSTOM" },
  }[kind];
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11, color: "var(--ink-2)" }}>
      <span style={{ color: k.color, display: "inline-flex" }}>{k.icon}</span>
      <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-3)", letterSpacing: "0.04em" }}>{k.prefix}</span>
      <span className="mono" style={{ fontSize: 11.5, color: "var(--ink-2)" }}>{label}</span>
    </span>
  );
}

export function Sparkline({ value, max = 1500 }: { value: number; max?: number }) {
  const pct = Math.min(100, Math.max(4, (value / max) * 100));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3, alignItems: "flex-end" }}>
      <span className="mono" style={{ fontSize: 11.5, color: "var(--ink-2)", fontWeight: 500 }}>{value.toLocaleString()}</span>
      <div style={{ width: 56, height: 3, background: "var(--surface-2)", borderRadius: 2, overflow: "hidden" }}>
        <div style={{ width: pct + "%", height: "100%", background: "var(--ink-3)" }}/>
      </div>
    </div>
  );
}

/* ── Skill type (matches Java DTO snake_case wire) ──────────────────
 *
 * Phase 11 v3 schema (doc-style):
 *
 *   { type: "event",    event: "OOC", target: {kind:"all", ids:[]} }
 *   { type: "schedule", schedule: {mode:"hourly", every: 4},
 *                       target: {kind:"tools", ids:["EQP-01","EQP-02"]} }
 *
 * Old v1/v2 fields (system / event_type / scope / cron / sla_seconds / ...)
 * are kept on the type so loaders can read legacy DB rows; on save we
 * re-emit only the v3 fields. See Playbook.tsx::migrateTrigger for the
 * one-shot upgrade path.
 */
export interface TriggerConfig {
  // ── v3 canonical fields ────────────────────────────────────────────
  type?: "event" | "schedule" | "user" | "system";   // "system" is legacy-alias for "event"
  event?: string;                  // when type==="event" — name from event_types
  schedule?: {
    mode?: "hourly" | "daily";
    every?: number;                // hourly mode
    time?: string;                 // daily mode "HH:MM"
  };
  target?: {
    kind: "all" | "tools" | "stations";
    ids: string[];
  };

  // ── Legacy fields (deprecated, retained for backward-compat read) ──
  // system → event
  event_type?: string;
  match_filter?: Record<string, unknown>;
  scope?: string;
  // user (still allowed, hidden from author UI in v3)
  name?: string;
  source?: string;
  metric?: string;
  op?: string;
  value?: string;
  window?: string;
  debounce?: string;
  severity?: string;
  // schedule (legacy flat fields → schedule.*)
  cron?: string;
  every?: number;
  unit?: "minute" | "hour" | "day";
  timezone?: string;
  align?: boolean;
  skip?: string[];
  // v2 header summary — dropped from UI in v3
  sla_seconds?: number;
  evidence_window_lots?: number;
  evidence_window_days?: number;
}

export interface SuggestedAction {
  id: string;
  title: string;
  detail: string;
  rationale?: string;
  confidence: "high" | "med" | "low";
}

export interface SkillStep {
  id: string;
  order: number;
  text: string;
  ai_summary?: string;
  pipeline_id?: number | null;
  confirmed?: boolean;
  pending?: boolean;
  suggested_actions?: SuggestedAction[];
  badge?: { kind: string; label: string };
}

export interface SkillStats {
  rating_avg?: number;
  runs_total?: number;
  runs_30d?: number;
  last_run_at?: string;
}

export interface SkillSummary {
  id: number;
  slug: string;
  title: string;
  version: string;
  stage: "patrol" | "diagnose";
  domain: string;
  description: string;
  status: string;
  certified_by?: string | null;
  author_user_id?: number | null;
  trigger_config: string;     // JSON string
  stats: string;               // JSON string
  updated_at: string;
}

export interface SkillDetail extends SkillSummary {
  steps: string;               // JSON string of SkillStep[]
  test_cases: string;
  created_at: string;
  confirm_check?: string | null;   // Phase 11 v2 — JSON string or null
}

/** Phase 11 v2 — optional CONFIRM (gating) step shape. */
export interface ConfirmCheck {
  description: string;
  ai_summary?: string;
  pipeline_id: number | null;
  must_pass?: boolean;
}

export function safeParse<T>(s: string | undefined | null, fallback: T): T {
  if (!s) return fallback;
  try {
    return JSON.parse(s) as T;
  } catch {
    return fallback;
  }
}

export const fmtCSS: Record<string, CSSProperties> = {};
