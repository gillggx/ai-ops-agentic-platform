"use client";

import { Sparkline } from "./Sparkline";
import type { Cluster } from "./types";

const SEV_LABEL: Record<string, string> = {
  critical: "CRIT",
  high: "HIGH",
  med: "MED",
  low: "LOW",
};

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return `${Math.floor(diff)}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return `${Math.floor(diff / 86400)}d`;
}

export function ClusterCard({ cluster, selected, onClick }: {
  cluster: Cluster;
  selected: boolean;
  onClick: () => void;
}) {
  const sevClass = `sev-${cluster.severity}`;
  return (
    <div
      className={"cluster-card " + sevClass + (selected ? " cluster-card--selected" : "")}
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(); } }}
    >
      <div className="cluster-card__bar" />
      <div>
        <div className="cluster-card__head">
          <span className="cluster-card__sev-tag">{SEV_LABEL[cluster.severity] ?? "—"}</span>
          <span className="cluster-card__tool">{cluster.equipment_id}</span>
          {cluster.bay && <span className="cluster-card__bay">BAY-{cluster.bay}</span>}
          <span className="cluster-card__time">{timeAgo(cluster.last_at)}</span>
        </div>
        <div className="cluster-card__title">{cluster.title}</div>
        <div className="cluster-card__foot">
          <span className="stat"><strong>{cluster.count}</strong> alarms</span>
          {cluster.affected_lots > 0 && (
            <span className="stat"><strong>{cluster.affected_lots}</strong> lots</span>
          )}
          {cluster.cause && (
            <span className="stat" title="cause">{cluster.cause}</span>
          )}
          <span style={{ marginLeft: "auto" }}>
            <Sparkline values={cluster.spark} />
          </span>
        </div>
      </div>
    </div>
  );
}
