"use client";

import { useEffect, useMemo, useState } from "react";
import { AlarmDetail, type Alarm } from "./AlarmDetailLegacy";
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

export function ClusterDetailPanel({ cluster, fullAlarms, loading }: {
  cluster: Cluster | null;
  fullAlarms: Alarm[];               // alarms in this cluster, full enrichment
  loading: boolean;
}) {
  const [selectedAlarmId, setSelectedAlarmId] = useState<number | null>(null);

  // Auto-select first alarm whenever cluster changes.
  useEffect(() => {
    if (cluster && fullAlarms.length > 0) setSelectedAlarmId(fullAlarms[0].id);
    else setSelectedAlarmId(null);
  }, [cluster?.cluster_id, fullAlarms]);

  const selected = useMemo(
    () => fullAlarms.find(a => a.id === selectedAlarmId) ?? null,
    [fullAlarms, selectedAlarmId]
  );

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
          {cluster.equipment_id} <span style={{ color: "var(--text-3)", fontWeight: 400, fontSize: 13 }}>({SEV_LABEL[cluster.severity] ?? cluster.severity})</span>
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
      </header>

      <section style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 11, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6, fontFamily: "var(--font-mono)" }}>
          {cluster.count} alarms · {fullAlarms.length} loaded
        </div>
        {loading && fullAlarms.length === 0 && (
          <div style={{ padding: 24, color: "var(--text-3)", textAlign: "center", fontSize: 13 }}>載入告警中…</div>
        )}
        {fullAlarms.map(a => (
          <div
            key={a.id}
            className={"alarm-row" + (selectedAlarmId === a.id ? " alarm-row--selected" : "")}
            onClick={() => setSelectedAlarmId(a.id)}
            role="button"
            tabIndex={0}
          >
            <div className="alarm-row__head">
              <span style={{ color: "var(--text)", fontWeight: 600 }}>#{a.id}</span>
              <span>{a.severity}</span>
              <span>{a.status}</span>
              <span style={{ marginLeft: "auto" }}>{new Date(a.created_at).toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit" })}</span>
            </div>
            <div className="alarm-row__title">{a.title}</div>
          </div>
        ))}
      </section>

      {selected && (
        <section style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, padding: 18 }}>
          <AlarmDetail alarm={selected} />
        </section>
      )}
    </main>
  );
}
