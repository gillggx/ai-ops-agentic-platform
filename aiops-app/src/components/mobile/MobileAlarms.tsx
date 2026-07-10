"use client";

/**
 * 手機 1a 告警戰情・叢集清單 — KPI 橫向捲動列＋嚴重度篩選＋每台一張卡。
 * 點卡進 1b（MobileAlarmDetail）。資料走既有 /api/admin/alarms/{kpis,clusters}。
 */
import { useCallback, useEffect, useState } from "react";
import { M, cardStyle, sevTone, ageLabel } from "./tokens";

export interface MobileCluster {
  cluster_id: string; equipment_id: string; severity: string;
  title: string; summary: string; count: number; open_count: number;
  ack_count: number; affected_lots: number; first_at: string; last_at: string;
  spark: number[]; cause: string; alarm_ids: number[];
  trigger_events?: string[];
}
interface Kpis {
  active_alarms: number; open_clusters: number; high_severity_count: number;
  health_score: number;
}

function Spark({ v }: { v: number[] }) {
  const max = Math.max(1, ...v);
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 1.5, height: 16, width: 74 }}>
      {v.slice(-18).map((x, i) => (
        <span key={i} style={{
          flex: 1, borderRadius: 1, minHeight: 2,
          height: `${Math.max(12, (x / max) * 100)}%`,
          background: x === 0 ? "#e9e6dd" : M.high,
          opacity: x === 0 ? 1 : 0.45 + 0.55 * (x / max),
        }} />
      ))}
    </div>
  );
}

export function MobileAlarms({ onOpenCluster }: { onOpenCluster: (c: MobileCluster) => void }) {
  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [clusters, setClusters] = useState<MobileCluster[]>([]);
  const [chip, setChip] = useState<"all" | "high" | "med" | "low">("all");

  const load = useCallback(() => {
    fetch("/api/admin/alarms/kpis?since_hours=24", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((env) => { const d = env?.data ?? env; if (d) setKpis(d as Kpis); })
      .catch(() => { /* ambient */ });
    fetch("/api/admin/alarms/clusters?since_hours=24&status=active", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((env) => {
        const d = env?.data ?? env;
        if (Array.isArray(d?.clusters)) setClusters(d.clusters as MobileCluster[]);
      })
      .catch(() => { /* ambient */ });
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 60_000); return () => clearInterval(t); }, [load]);

  const isHigh = (s: string) => ["critical", "high"].includes(s.toLowerCase());
  const isMed = (s: string) => ["med", "medium"].includes(s.toLowerCase());
  const counts = {
    high: clusters.filter((c) => isHigh(c.severity)).length,
    med: clusters.filter((c) => isMed(c.severity)).length,
    low: clusters.filter((c) => !isHigh(c.severity) && !isMed(c.severity)).length,
  };
  const shown = clusters.filter((c) =>
    chip === "all" ? true : chip === "high" ? isHigh(c.severity) : chip === "med" ? isMed(c.severity)
    : !isHigh(c.severity) && !isMed(c.severity));
  const totalAlarms = clusters.reduce((s, c) => s + c.count, 0);

  return (
    <div style={{ padding: "14px 14px 90px", fontFamily: M.sans, color: M.ink }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ width: 9, height: 9, borderRadius: "50%", background: M.crit }} />
        <span style={{ fontSize: 21, fontWeight: 800 }}>AI 戰況</span>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 10.5, color: M.faint, fontFamily: M.mono }}>refreshed 60s</span>
      </div>

      {/* KPI 橫向捲動 */}
      {kpis && (
        <div style={{ display: "flex", gap: 8, overflowX: "auto", margin: "12px -14px 0", padding: "0 14px 4px" }}>
          {([
            ["ACTIVE ALARMS", kpis.active_alarms, M.ink],
            ["OPEN CLUSTERS", kpis.open_clusters, M.ink],
            ["HIGH SEVERITY", kpis.high_severity_count, M.high],
            ["HEALTH", kpis.health_score, M.ok],
          ] as const).map(([label, v, color]) => (
            <div key={label} style={{ ...cardStyle, padding: "10px 14px", minWidth: 116, flexShrink: 0 }}>
              <div style={{ fontSize: 9, fontFamily: M.mono, letterSpacing: ".06em", color: M.faint }}>{label}</div>
              <div style={{ fontFamily: M.mono, fontSize: 22, fontWeight: 700, color, marginTop: 2 }}>{v}</div>
            </div>
          ))}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "baseline", margin: "14px 0 8px" }}>
        <span style={{ fontSize: 10.5, fontFamily: M.mono, letterSpacing: ".08em", color: M.faint }}>
          CLUSTERS ・ {shown.length}/{clusters.length}
        </span>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 10.5, fontFamily: M.mono, color: M.faint }}>{totalAlarms} ALARMS</span>
      </div>

      <div style={{ display: "flex", gap: 7, marginBottom: 10 }}>
        {([["all", `全部 ${clusters.length}`], ["high", `High ${counts.high}`],
           ["med", `Med ${counts.med}`], ["low", `Low ${counts.low}`]] as const).map(([k, label]) => (
          <button key={k} onClick={() => setChip(k)} style={{
            border: "none", borderRadius: 16, padding: "6px 12px", fontSize: 12, fontWeight: 700,
            cursor: "pointer",
            background: chip === k ? M.ink : "#fff",
            color: chip === k ? "#fff" : M.sub,
            boxShadow: chip === k ? "none" : `inset 0 0 0 1px ${M.line}`,
          }}>{label}</button>
        ))}
      </div>

      {shown.map((c) => {
        const tone = sevTone(c.severity);
        return (
          <div key={c.cluster_id} onClick={() => onOpenCluster(c)} style={{
            ...cardStyle, padding: "12px 14px", marginBottom: 9,
            borderLeft: `3px solid ${tone.fg}`, cursor: "pointer",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{
                fontSize: 9.5, fontWeight: 700, fontFamily: M.mono, padding: "1px 7px",
                borderRadius: 4, color: tone.fg, background: tone.bg,
              }}>{tone.label}</span>
              <span style={{ fontFamily: M.mono, fontSize: 15, fontWeight: 700 }}>{c.equipment_id}</span>
              <span style={{ flex: 1 }} />
              <span style={{ fontFamily: M.mono, fontSize: 11, color: M.faint }}>{ageLabel(c.last_at)}</span>
            </div>
            <div style={{ fontSize: 13, marginTop: 6, lineHeight: 1.5 }}>{c.title || c.summary}</div>
            <div style={{ display: "flex", alignItems: "center", marginTop: 7 }}>
              <span style={{ fontFamily: M.mono, fontSize: 11, color: M.sub }}>
                {c.count} alarms {c.cause ? `・ ${c.cause}` : ""}
              </span>
              <span style={{ flex: 1 }} />
              <Spark v={c.spark ?? []} />
            </div>
          </div>
        );
      })}
      {shown.length === 0 && (
        <div style={{ padding: 24, textAlign: "center", color: M.faint, fontSize: 12.5 }}>
          目前沒有符合的告警叢集
        </div>
      )}
    </div>
  );
}
