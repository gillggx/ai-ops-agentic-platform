"use client";

import { useTranslations } from "next-intl";
import type { Kpis } from "./types";

/** AI 戰況 — auto_check throughput strip. Tier 1 placeholder uses live
 *  KPI counts; future versions can stream auto_check completions via SSE. */
export function PulseStrip({ kpis }: { kpis: Kpis | null }) {
  const t = useTranslations("alarms");
  const runs = kpis?.auto_check_runs_last_hour ?? 0;
  const lat = kpis?.auto_check_avg_latency_s ?? null;
  const high = kpis?.high_severity_count ?? 0;
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>;
  return (
    <div className="alarm-center__pulse-strip">
      <span className={"pulse-dot" + (high > 0 ? " pulse-dot--high" : "")} />
      <span style={{ fontWeight: 600, color: "var(--text)" }}>{t("pulse.title")}</span>
      <span className="pulse-divider" />
      <span className="pulse-stat">
        {t.rich("pulse.runsPerHour", { n: runs, strong })}
      </span>
      <span className="pulse-divider" />
      <span className="pulse-stat">
        {t.rich("pulse.avgLatency", { v: lat != null ? `${Math.max(0, lat).toFixed(1)}s` : "—", strong })}
      </span>
      <span className="pulse-divider" />
      <span className="pulse-stat">
        {t.rich("pulse.high", { n: high, strong })}
      </span>
      <div style={{ flex: 1 }} />
      <span style={{ color: "var(--text-3)" }}>{t("pulse.footer")}</span>
    </div>
  );
}
