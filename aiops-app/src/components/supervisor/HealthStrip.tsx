"use client";

/**
 * 健康總覽 strip — S1 執行健康 / S2 知識品質 / S3 成本與資源.
 *
 * S1 computed client-side from GET /api/agent-activity/episodes (success
 * rate, avg LLM calls, divergence count). S2 from proposal counts + doc
 * memo queue length. S3 from GET /api/supervisor/metrics/llm-daily?days=7:
 * today's calls, empty-rate (aggregated across all models, red when > 10%)
 * and cache_read tokens. Pricing is not wired yet so the cost cell stays
 * "—" (never fabricate); old backends without the endpoint fail-open to
 * placeholders.
 */

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { TOK, LlmDailyRow, api } from "./model";

interface EpisodeRow {
  status: string | null;
  divergence: boolean;
  cost: Record<string, unknown> | null;
}

interface S1 { successRate: string; avgCalls: string; divergence: string }
interface S2 { pending: string; docMemos: string }
interface S3 { calls: string; emptyRate: string; emptyHot: boolean; cacheRead: string }

const EPISODE_WINDOW = 50;
const EMPTY_RATE_RED_PCT = 10;
const DASH = "—";

/** 12345678 → "12.3M", 45210 → "45.2k" — mono metric stays short. */
function fmtCompact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

const cardStyle: React.CSSProperties = {
  background: TOK.card, border: `1px solid ${TOK.border}`, borderRadius: 10,
  padding: "12px 16px",
};

function Metric({ value, label, hot }: { value: string; label: string; hot?: boolean }) {
  return (
    <div>
      <div style={{ font: `700 20px ${TOK.mono}`, color: hot ? TOK.red : TOK.ink }}>{value}</div>
      <div style={{ fontSize: 10.5, color: hot ? TOK.red : TOK.muted }}>{label}</div>
    </div>
  );
}

function CardHead({ tag, tagColor, title, note }: {
  tag: string; tagColor: string; title: string; note?: string;
}) {
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
      <span style={{ font: `700 11px ${TOK.mono}`, color: tagColor }}>{tag}</span>
      <span style={{ fontSize: 12, fontWeight: 600 }}>{title}</span>
      <span style={{ flex: 1 }} />
      {note && <span style={{ font: `500 10px ${TOK.mono}`, color: TOK.faint }}>{note}</span>}
    </div>
  );
}

export function HealthStrip({ refreshKey }: { refreshKey: number }) {
  const t = useTranslations("sup");
  const [s1, setS1] = useState<S1>({ successRate: DASH, avgCalls: DASH, divergence: DASH });
  const [s2, setS2] = useState<S2>({ pending: DASH, docMemos: DASH });
  const [s3, setS3] = useState<S3>({ calls: DASH, emptyRate: DASH, emptyHot: false, cacheRead: DASH });
  const [updatedAt, setUpdatedAt] = useState<string>(DASH);

  useEffect(() => {
    let alive = true;

    // S1 — episodes list: { episode_key, status, divergence, step_count, cost }
    api<EpisodeRow[]>(`/api/agent-activity/episodes?limit=${EPISODE_WINDOW}`)
      .then((rows) => {
        if (!alive || !Array.isArray(rows)) return;
        const done = rows.filter((r) => r.status === "success" || r.status === "failed");
        const ok = done.filter((r) => r.status === "success").length;
        const calls = rows
          .map((r) => Object.values(r.cost ?? {}).reduce<number>((acc, v) => {
            const c = (v as Record<string, unknown> | null)?.calls;
            return acc + (typeof c === "number" ? c : 0);
          }, 0))
          .filter((n) => n > 0);
        setS1({
          successRate: done.length > 0 ? `${Math.round((ok / done.length) * 100)}%` : DASH,
          avgCalls: calls.length > 0
            ? (calls.reduce((a, b) => a + b, 0) / calls.length).toFixed(1)
            : DASH,
          divergence: String(rows.filter((r) => r.divergence).length),
        });
      })
      .catch(() => { /* fail-open — strip shows placeholders */ });

    // S2 — pending proposals + Builder doc memo queue length
    api<{ proposed?: number }>("/api/supervisor/proposals/counts")
      .then((c) => { if (alive && c && typeof c.proposed === "number") setS2((s) => ({ ...s, pending: String(c.proposed) })); })
      .catch(() => {});
    api<unknown[]>("/api/agent-knowledge/doc-memos")
      .then((memos) => { if (alive && Array.isArray(memos)) setS2((s) => ({ ...s, docMemos: String(memos.length) })); })
      .catch(() => {});

    // S3 — daily LLM metrics (W2). "Today" = the newest day in the window;
    // aggregate across all models. Endpoint may not exist yet → fail-open.
    api<LlmDailyRow[]>("/api/supervisor/metrics/llm-daily?days=7")
      .then((rows) => {
        if (!alive || !Array.isArray(rows) || rows.length === 0) return;
        const days = rows.map((r) => r.day ?? "").filter(Boolean);
        if (days.length === 0) return;
        const today = days.sort().at(-1);
        const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : 0);
        const t3 = rows.filter((r) => (r.day ?? "") === today);
        const calls = t3.reduce((a, r) => a + num(r.calls), 0);
        const empty = t3.reduce((a, r) => a + num(r.empty_calls), 0);
        const cacheRead = t3.reduce((a, r) => a + num(r.cache_read), 0);
        const pct = calls > 0 ? (empty / calls) * 100 : null;
        setS3({
          calls: String(calls),
          emptyRate: pct == null ? DASH : `${pct.toFixed(1)}%`,
          emptyHot: pct != null && pct > EMPTY_RATE_RED_PCT,
          cacheRead: fmtCompact(cacheRead),
        });
      })
      .catch(() => { /* fail-open — S3 keeps placeholders */ });

    setUpdatedAt(new Date().toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }));
    return () => { alive = false; };
  }, [refreshKey]);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 10 }}>
        <span style={{ fontSize: 13, fontWeight: 700 }}>{t("health.title")}</span>
        <span style={{ flex: 1 }} />
        <span style={{ font: `500 11px ${TOK.mono}`, color: TOK.muted }}>
          {t("health.updatedAt", { time: updatedAt })}
        </span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1.2fr", gap: 12, marginBottom: 20 }}>
        <div style={cardStyle}>
          <CardHead tag="S1" tagColor={TOK.blue} title={t("health.s1Title")} />
          <div style={{ display: "flex", gap: 22 }}>
            <Metric value={s1.successRate} label={t("health.s1SuccessRate", { n: EPISODE_WINDOW })} />
            <Metric value={s1.avgCalls} label={t("health.s1AvgRounds")} />
            <Metric value={s1.divergence} label={t("health.s1Divergence")} />
          </div>
        </div>
        <div style={cardStyle}>
          <CardHead tag="S2" tagColor={TOK.purple} title={t("health.s2Title")} />
          <div style={{ display: "flex", gap: 22 }}>
            <Metric value={s2.pending} label={t("health.s2Pending")} />
            <Metric value={s2.docMemos} label={t("health.s2DocMemos")} />
            {/* recall hit-rate needs the W2 metrics backend — placeholder */}
            <Metric value={DASH} label={t("health.s2RecallRate")} />
          </div>
        </div>
        <div style={cardStyle}>
          <CardHead tag="S3" tagColor={TOK.cyan} title={t("health.s3Title")} note={t("health.s3Note")} />
          <div style={{ display: "flex", gap: 22 }}>
            {/* tokens are on the wire but pricing is not — cost stays "—" */}
            <Metric value={DASH} label={t("health.s3Cost")} />
            <Metric value={s3.calls} label={t("health.s3Calls")} />
            <Metric value={s3.emptyRate} hot={s3.emptyHot} label={t("health.s3Empty")} />
            <Metric value={s3.cacheRead} label={t("health.s3CacheRead")} />
          </div>
        </div>
      </div>
    </div>
  );
}
