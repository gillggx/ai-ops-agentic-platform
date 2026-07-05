"use client";

/**
 * 健康總覽 strip — S1 執行健康 / S2 知識品質 / S3 成本與資源.
 *
 * S1 computed client-side from GET /api/agent-activity/episodes (success
 * rate, avg LLM calls, divergence count). S2 from proposal counts + doc
 * memo queue length. S3 is a W2 placeholder — the visual slot is kept per
 * design but values stay "—" until the cost backend lands (never fabricate).
 */

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { TOK, api } from "./model";

interface EpisodeRow {
  status: string | null;
  divergence: boolean;
  cost: Record<string, unknown> | null;
}

interface S1 { successRate: string; avgCalls: string; divergence: string }
interface S2 { pending: string; docMemos: string }

const EPISODE_WINDOW = 50;
const DASH = "—";

const cardStyle: React.CSSProperties = {
  background: TOK.card, border: `1px solid ${TOK.border}`, borderRadius: 10,
  padding: "12px 16px",
};

function Metric({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <div style={{ font: `700 20px ${TOK.mono}`, color: TOK.ink }}>{value}</div>
      <div style={{ fontSize: 10.5, color: TOK.muted }}>{label}</div>
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
            {/* W2 cost backend not wired yet — keep the design slots, show "—" */}
            <Metric value={DASH} label={t("health.s3Cost")} />
            <Metric value={DASH} label={t("health.s3Cache")} />
            <Metric value={DASH} label={t("health.s3Empty")} />
          </div>
        </div>
      </div>
    </div>
  );
}
