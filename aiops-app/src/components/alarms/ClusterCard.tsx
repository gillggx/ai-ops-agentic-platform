"use client";

import { useTranslations } from "next-intl";
import { Sparkline } from "./Sparkline";
import type { Cluster } from "./types";

const KNOWN_SEVERITIES = ["critical", "high", "med", "low"] as const;

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
  const t = useTranslations("alarms");
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>;
  const sevClass = `sev-${cluster.severity}`;
  const sevLabel = (KNOWN_SEVERITIES as readonly string[]).includes(cluster.severity)
    ? t(`sevShort.${cluster.severity}`)
    : "—";
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
          <span className="cluster-card__sev-tag">{sevLabel}</span>
          <span className="cluster-card__tool">{cluster.equipment_id}</span>
          <span className="cluster-card__time">{timeAgo(cluster.last_at)}</span>
        </div>
        <div className="cluster-card__title">{cluster.title}</div>
        <div className="cluster-card__foot">
          <span className="stat">{t.rich("card.alarms", { n: cluster.count, strong })}</span>
          {cluster.affected_lots > 0 && (
            <span className="stat">{t.rich("card.lots", { n: cluster.affected_lots, strong })}</span>
          )}
          {cluster.cause && (
            <span className="stat" title={t("card.causeTooltip")}>{cluster.cause}</span>
          )}
          <span style={{ marginLeft: "auto" }}>
            <Sparkline values={cluster.spark} />
          </span>
        </div>
      </div>
    </div>
  );
}
