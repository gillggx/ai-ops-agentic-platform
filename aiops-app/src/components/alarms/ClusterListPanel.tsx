"use client";

import { useMemo } from "react";
import { ClusterCard } from "./ClusterCard";
import type { Cluster, Severity } from "./types";

type SevFilter = "all" | "high" | "med" | "low";

export function ClusterListPanel({
  clusters, totalAlarms, sevFilter, setSevFilter,
  selectedClusterId, onSelect, loading,
}: {
  clusters: Cluster[];
  totalAlarms: number;
  sevFilter: SevFilter;
  setSevFilter: (s: SevFilter) => void;
  selectedClusterId: string | null;
  onSelect: (id: string) => void;
  loading: boolean;
}) {
  const filtered = useMemo(() => clusters.filter(c => {
    if (sevFilter !== "all") {
      const matchSev: Record<SevFilter, Severity[]> = {
        all: ["critical", "high", "med", "low"],
        high: ["critical", "high"],
        med: ["med"],
        low: ["low"],
      };
      if (!matchSev[sevFilter].includes(c.severity)) return false;
    }
    return true;
  }), [clusters, sevFilter]);

  const sevCounts = useMemo(() => {
    const c = { all: clusters.length, high: 0, med: 0, low: 0 };
    for (const cl of clusters) {
      if (cl.severity === "high" || cl.severity === "critical") c.high++;
      else if (cl.severity === "med") c.med++;
      else if (cl.severity === "low") c.low++;
    }
    return c;
  }, [clusters]);

  return (
    <aside className="alarm-center__list" aria-label="Cluster list">
      <div className="alarm-center__list-header">
        <span>Clusters · {filtered.length}/{clusters.length}</span>
        <span style={{ color: "var(--text-4)" }}>{totalAlarms} alarms</span>
      </div>
      <div className="alarm-center__list-filters">
        {([
          ["all", "全部", sevCounts.all],
          ["high", "High", sevCounts.high],
          ["med", "Med", sevCounts.med],
          ["low", "Low", sevCounts.low],
        ] as const).map(([key, label, n]) => (
          <button key={key} className={"chip" + (sevFilter === key ? " chip--active" : "")} onClick={() => setSevFilter(key as SevFilter)}>
            {label} <span className="chip__count">{n}</span>
          </button>
        ))}
      </div>
      <div className="alarm-center__list-body">
        {loading && filtered.length === 0 && (
          <div className="alarm-center__empty">載入中…</div>
        )}
        {!loading && filtered.length === 0 && (
          <div className="alarm-center__empty">
            <div>
              <div style={{ fontSize: 32, marginBottom: 8 }}>✅</div>
              <div>沒有符合條件的告警</div>
            </div>
          </div>
        )}
        {filtered.map(c => (
          <ClusterCard
            key={c.cluster_id}
            cluster={c}
            selected={selectedClusterId === c.cluster_id}
            onClick={() => onSelect(c.cluster_id)}
          />
        ))}
      </div>
    </aside>
  );
}
