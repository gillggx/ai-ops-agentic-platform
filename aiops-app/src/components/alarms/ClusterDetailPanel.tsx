"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import { useBriefing } from "./AlarmDetailLegacy";
import type { Cluster } from "./types";

const SEV_LABEL: Record<string, string> = {
  critical: "CRITICAL", high: "HIGH", med: "MED", low: "LOW",
};

function fmtDateRange(first: string | null, last: string | null): string {
  if (!first || !last) return "—";
  const f = new Date(first), l = new Date(last);
  const sameDay = f.toDateString() === l.toDateString();
  const t = (d: Date) => d.toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit" });
  if (sameDay) return `${f.toLocaleDateString("zh-TW")} ${t(f)} → ${t(l)}`;
  return `${f.toLocaleDateString("zh-TW")} ${t(f)} → ${l.toLocaleDateString("zh-TW")} ${t(l)}`;
}

export function ClusterDetailPanel({ cluster, onAcked }: {
  cluster: Cluster | null;
  onAcked: (count: number) => void;
}) {
  // Cluster-level briefing — feed cluster aggregates into the existing
  // queue-style briefing scope. Sidecar prompt already speaks "alarm
  // queue" so this lights up "AI 綜合診斷" with the same shape it had
  // at queue level, just scoped to one cluster.
  const briefingData = useMemo(() => cluster ? JSON.stringify({
    total: cluster.count,
    severities: { [cluster.severity]: cluster.count },
    top_equipment: [{ equipment_id: cluster.equipment_id, count: cluster.count }],
    cluster_focus: {
      equipment_id: cluster.equipment_id,
      bay: cluster.bay,
      first_at: cluster.first_at,
      last_at: cluster.last_at,
      affected_lots: cluster.affected_lots,
      cause: cluster.cause,
      trigger_events: cluster.trigger_events,
    },
  }) : "", [cluster]);
  const synthesis = useBriefing("alarm", briefingData);

  // Refresh synthesis whenever the focused cluster changes.
  useEffect(() => { if (cluster) synthesis.refresh(); }, [cluster?.cluster_id]); // eslint-disable-line

  const [acking, setAcking] = useState(false);
  const [ackError, setAckError] = useState<string | null>(null);

  const ack = async () => {
    if (!cluster) return;
    setAcking(true);
    setAckError(null);
    try {
      const res = await fetch("/api/admin/alarms/cluster-ack", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ equipment_id: cluster.equipment_id }),
      });
      if (!res.ok) { setAckError(`HTTP ${res.status}`); return; }
      const j = await res.json();
      onAcked(j.acknowledged ?? 0);
    } catch (e) {
      setAckError(String(e));
    } finally { setAcking(false); }
  };

  if (!cluster) {
    return (
      <main className="alarm-center__detail">
        <div className="alarm-center__empty">
          <div>
            <div style={{ fontSize: 32, marginBottom: 8 }}>👈</div>
            <div>左側選擇 cluster 開始</div>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="alarm-center__detail" aria-label="Cluster detail">
      <header className="cluster-detail__head">
        <h1 className="cluster-detail__title">
          {cluster.equipment_id}
          {" "}
          <span style={{ color: "var(--text-3)", fontWeight: 400, fontSize: 13 }}>
            ({SEV_LABEL[cluster.severity] ?? cluster.severity})
          </span>
        </h1>
        <div className="cluster-detail__meta">
          <span><strong>{cluster.count}</strong> alarms</span>
          <span><strong>{cluster.open_count}</strong> open</span>
          {cluster.ack_count > 0 && <span><strong>{cluster.ack_count}</strong> acknowledged</span>}
          {cluster.affected_lots > 0 && <span><strong>{cluster.affected_lots}</strong> lots</span>}
          {cluster.bay && <span>BAY-{cluster.bay}</span>}
          <span style={{ flexBasis: "100%" }} />
          <span>{fmtDateRange(cluster.first_at, cluster.last_at)}</span>
          {cluster.cause && <span>cause: {cluster.cause}</span>}
        </div>
        <button
          className="cluster-detail__action"
          onClick={ack}
          disabled={acking || cluster.open_count === 0}
          title={cluster.open_count === 0 ? "沒有 open alarm" : `批次 acknowledge ${cluster.open_count} 個告警`}
        >
          {acking ? "處理中…" : `✓ Acknowledge · ${cluster.open_count}`}
        </button>
        {ackError && (
          <div style={{ position: "absolute", top: 48, right: 16, color: "var(--high)", fontSize: 11 }}>
            {ackError}
          </div>
        )}
      </header>

      {/* Cluster-level AI synthesis (was per-alarm). */}
      <section className="cluster-synthesis">
        <div className="cluster-synthesis__title">✨ AI 診斷報告 | {cluster.equipment_id}</div>
        <div className="cluster-synthesis__meta">
          {cluster.count} alarms · {SEV_LABEL[cluster.severity] ?? cluster.severity} · {fmtDateRange(cluster.first_at, cluster.last_at)}
        </div>
        <div className="cluster-synthesis__body">
          {synthesis.loading ? (
            <span className="cluster-synthesis__loading">
              <span style={{ display: "inline-block", width: 8, height: 14, background: "var(--accent)", animation: "blink 1s step-end infinite", marginRight: 6, verticalAlign: "text-bottom" }} />
              AI 正在綜合此 cluster 的所有告警…
            </span>
          ) : synthesis.text ? (
            <ReactMarkdown>{synthesis.text}</ReactMarkdown>
          ) : (
            <span className="cluster-synthesis__loading">（無診斷摘要）</span>
          )}
        </div>
      </section>

      {/* Compact alarm row list — click → drill-down to /alarms/[id]. */}
      <section>
        <div style={{ fontSize: 11, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8, fontFamily: "var(--font-mono)" }}>
          {cluster.count} alarms · 點任一筆進入深度診斷
        </div>
        {cluster.alarm_ids.length === 0 && (
          <div style={{ padding: 24, color: "var(--text-3)", textAlign: "center", fontSize: 13 }}>（無告警）</div>
        )}
        {cluster.alarm_ids.map(id => (
          <AlarmRowLink key={id} alarmId={id} cluster={cluster} />
        ))}
      </section>
    </main>
  );
}

/** Compact row — only the meta we have from the cluster aggregate.
 *  Title + severity come from the cluster summary (alarms in the same
 *  cluster share the same trigger pattern). Click → /alarms/[id]. */
function AlarmRowLink({ alarmId, cluster }: { alarmId: number; cluster: Cluster }) {
  return (
    <Link href={`/alarms/${alarmId}`} className="alarm-row" style={{ display: "block", textDecoration: "none", color: "inherit" }}>
      <div className="alarm-row__head">
        <span style={{ color: "var(--text)", fontWeight: 600 }}>#{alarmId}</span>
        <span>{SEV_LABEL[cluster.severity] ?? cluster.severity}</span>
        <span>{cluster.equipment_id}</span>
        <span className="alarm-row__link">進入深度診斷 →</span>
      </div>
      <div className="alarm-row__title">{cluster.title}</div>
    </Link>
  );
}
