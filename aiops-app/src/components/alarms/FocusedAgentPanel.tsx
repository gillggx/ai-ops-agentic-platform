"use client";

import { useState } from "react";
import type { Cluster } from "./types";
import type { Alarm, AutoCheckRun } from "./AlarmDetailLegacy";

/** Right pane: cluster summary + plan steps (from latest alarm's
 *  auto_check_runs) + batch-ack action. SPEC §2.7. */
export function FocusedAgentPanel({ cluster, fullAlarms, onAcked }: {
  cluster: Cluster | null;
  fullAlarms: Alarm[];
  onAcked: (count: number) => void;
}) {
  const [acking, setAcking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!cluster) {
    return (
      <aside className="alarm-center__copilot" aria-label="AI copilot">
        <div className="copilot__title">AI 助理</div>
        <div style={{ color: "var(--text-3)", fontSize: 12 }}>選擇 cluster 後顯示</div>
      </aside>
    );
  }

  // Pull plan from the latest alarm's auto_check_runs alert messages.
  const planSteps: { text: string; status: "alert" | "ok" }[] = [];
  for (const a of fullAlarms.slice(0, 1)) {
    for (const r of (a.auto_check_runs ?? []) as AutoCheckRun[]) {
      if (r.alert?.title) planSteps.push({ text: r.alert.title, status: "alert" });
      else if (r.pipeline_name) planSteps.push({ text: r.pipeline_name, status: "ok" });
    }
  }

  const ack = async () => {
    setAcking(true);
    setError(null);
    try {
      const res = await fetch("/api/admin/alarms/cluster-ack", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ equipment_id: cluster.equipment_id }),
      });
      if (!res.ok) { setError(`HTTP ${res.status}`); return; }
      const j = await res.json();
      onAcked(j.acknowledged ?? 0);
    } catch (e) {
      setError(String(e));
    } finally {
      setAcking(false);
    }
  };

  return (
    <aside className="alarm-center__copilot" aria-label="AI copilot">
      <div className="copilot__title">AI 助理 · {cluster.equipment_id}</div>

      <div className="copilot__group">
        <h4>Cluster 摘要</h4>
        <div className="stat-line"><span>Affected lots</span><strong>{cluster.affected_lots || "—"}</strong></div>
        <div className="stat-line"><span>First seen</span><strong>{cluster.first_at ? new Date(cluster.first_at).toLocaleString("zh-TW") : "—"}</strong></div>
        <div className="stat-line"><span>Cause</span><strong>{cluster.cause ?? "—"}</strong></div>
        <div className="stat-line"><span>Confidence</span><strong>{cluster.rootcause_confidence != null ? `${(cluster.rootcause_confidence * 100).toFixed(0)}%` : "—"}</strong></div>
        <div className="stat-line"><span>Trigger types</span><strong>{cluster.trigger_events.length}</strong></div>
      </div>

      {planSteps.length > 0 && (
        <div className="copilot__group">
          <h4>診斷計畫</h4>
          {planSteps.map((s, i) => (
            <div key={i} className="stat-line">
              <span>{s.status === "alert" ? "⚠" : "✓"} {s.text}</span>
            </div>
          ))}
        </div>
      )}

      <button
        className="copilot__action"
        onClick={ack}
        disabled={acking || cluster.open_count === 0}
        title={cluster.open_count === 0 ? "沒有 open alarm" : `Acknowledge cluster · ${cluster.open_count} alarms`}
      >
        {acking ? "處理中…" : `✓ Acknowledge cluster · ${cluster.open_count}`}
      </button>
      {error && <div style={{ color: "var(--high)", fontSize: 11, marginTop: 8 }}>{error}</div>}
    </aside>
  );
}
