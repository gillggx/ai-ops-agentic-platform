"use client";

/**
 * 手機 1c 全廠總覽 — AI 簡報卡（可重新生成）＋整體指標 2 欄＋需介入機台卡片列。
 * 資料全部走既有桌機 API（fleet stats / equipment / briefing SSE）。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useBriefing } from "@/components/alarms/AlarmDetailLegacy";
import { M, cardStyle } from "./tokens";

interface FleetEquipment {
  id: string; name: string; health: "crit" | "warn" | "healthy";
  score: number; ooc: number; ooc_count: number; alarms: number;
  fdc: number; lots24h: number; trend: "up" | "down" | "flat";
  note: string; hourly: number[];
}
interface FleetStats {
  fleet_ooc_rate: number; ooc_events: number; total_events: number;
  fdc_alerts: number; open_alarms: number; affected_lots: number;
  crit_count: number; warn_count: number; as_of: string;
}

const HEALTH_DOT: Record<string, string> = { crit: M.crit, warn: M.med, healthy: M.ok };

function HeatStrip({ hourly }: { hourly: number[] }) {
  const max = Math.max(1, ...hourly);
  return (
    <div style={{ display: "flex", gap: 2, margin: "6px 0 4px" }}>
      {hourly.map((v, i) => {
        const r = v / max;
        const bg = v === 0 ? "#e9e6dd" : r > 0.66 ? M.high : r > 0.33 ? M.med : "#d9c9a5";
        return <span key={i} style={{ flex: 1, height: 9, borderRadius: 2, background: bg }} />;
      })}
    </div>
  );
}

export function MobileOverview({ onOpenEqp, onOpenAlarms }: {
  onOpenEqp: (id: string) => void;
  onOpenAlarms: () => void;
}) {
  const [stats, setStats] = useState<FleetStats | null>(null);
  const [eqps, setEqps] = useState<FleetEquipment[]>([]);
  const [chip, setChip] = useState<"all" | "crit" | "warn">("all");
  const briefing = useBriefing("fab", undefined, "mobile-fab");

  const load = useCallback(() => {
    fetch("/api/admin/fleet/stats?since_hours=24", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((env) => { const d = env?.data ?? env; if (d) setStats(d as FleetStats); })
      .catch(() => { /* ambient */ });
    fetch("/api/admin/fleet/equipment?since_hours=24", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((env) => {
        const d = env?.data ?? env;
        if (Array.isArray(d?.equipment)) setEqps(d.equipment as FleetEquipment[]);
      })
      .catch(() => { /* ambient */ });
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 60_000); return () => clearInterval(t); }, [load]);
  useEffect(() => { void briefing.refresh(); /* cached 10min */ // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const ordered = useMemo(() => {
    const rank = { crit: 0, warn: 1, healthy: 2 } as const;
    return [...eqps].sort((a, b) => rank[a.health] - rank[b.health] || b.ooc - a.ooc);
  }, [eqps]);
  const shown = ordered.filter((e) => chip === "all" || e.health === chip);
  const critN = eqps.filter((e) => e.health === "crit").length;
  const warnN = eqps.filter((e) => e.health === "warn").length;

  const asOf = stats?.as_of ? new Date(stats.as_of) : null;

  return (
    <div style={{ padding: "14px 14px 90px", fontFamily: M.sans, color: M.ink }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <div style={{ fontSize: 21, fontWeight: 800 }}>全廠總覽</div>
        <div style={{ fontSize: 10.5, color: M.faint, fontFamily: M.mono, textAlign: "right" }}>
          近24小時<br />更新 {asOf ? `${String(asOf.getHours()).padStart(2, "0")}:${String(asOf.getMinutes()).padStart(2, "0")}` : "—"}
        </div>
      </div>

      {/* AI 簡報 */}
      <div style={{ ...cardStyle, marginTop: 12, padding: "12px 14px", borderLeft: `3px solid ${M.ai}` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <span style={{ fontSize: 13, fontWeight: 800, color: M.ai }}>✦ AI 簡報</span>
          <span style={{ flex: 1 }} />
          <button onClick={() => void briefing.refresh(true)} style={{
            border: "none", background: "none", color: M.ai, fontSize: 11.5,
            fontWeight: 700, cursor: "pointer", padding: 0,
          }}>
            重新生成
          </button>
        </div>
        <div style={{ fontSize: 13.5, lineHeight: 1.75, marginTop: 7, whiteSpace: "pre-wrap" }}>
          {briefing.text || (briefing.loading ? "AI 正在整理全廠狀況…" : "尚無簡報 — 點「重新生成」。")}
        </div>
      </div>

      {/* 整體指標 */}
      {stats && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 9, marginTop: 10 }}>
          <div style={{ ...cardStyle, padding: "11px 13px" }}>
            <div style={kpiLabel}>OOC Rate</div>
            <div style={{ ...kpiValue, color: M.high }}>{stats.fleet_ooc_rate.toFixed(2)}%</div>
          </div>
          <div style={{ ...cardStyle, padding: "11px 13px" }}>
            <div style={kpiLabel}>OOC events</div>
            <div style={{ ...kpiValue, color: M.med }}>{stats.ooc_events}</div>
          </div>
          <div style={{ ...cardStyle, padding: "11px 13px", cursor: "pointer" }} onClick={onOpenAlarms}>
            <div style={kpiLabel}>Open alarms（點進戰情）</div>
            <div style={{ ...kpiValue, color: M.high }}>{stats.open_alarms}</div>
          </div>
          <div style={{ ...cardStyle, padding: "11px 13px" }}>
            <div style={kpiLabel}>受影響 LOT・FDC</div>
            <div style={kpiValue}>{stats.affected_lots} <span style={{ color: M.faint }}>・</span> {stats.fdc_alerts}</div>
          </div>
        </div>
      )}

      {/* 需介入機台 */}
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, margin: "18px 0 8px" }}>
        <span style={{ fontSize: 14.5, fontWeight: 800 }}>需介入機台</span>
        <span style={{ fontSize: 10.5, color: M.faint }}>依嚴重度排序</span>
      </div>
      <div style={{ display: "flex", gap: 7, marginBottom: 10 }}>
        {([["all", `全部 ${eqps.length}`], ["crit", `需介入 ${critN}`], ["warn", `關注 ${warnN}`]] as const).map(([k, label]) => (
          <button key={k} onClick={() => setChip(k)} style={{
            border: "none", borderRadius: 16, padding: "6px 13px", fontSize: 12, fontWeight: 700,
            cursor: "pointer",
            background: chip === k ? M.ink : "#fff",
            color: chip === k ? "#fff" : M.sub,
            boxShadow: chip === k ? "none" : `inset 0 0 0 1px ${M.line}`,
          }}>{label}</button>
        ))}
      </div>

      {shown.map((e, i) => {
        const worse = e.trend === "up";
        const better = e.trend === "down";
        return (
          <div key={e.id} style={{ ...cardStyle, padding: "12px 14px", marginBottom: 9 }}
               onClick={() => onOpenEqp(e.id)}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontFamily: M.mono, fontSize: 11, color: M.faint }}>{String(i + 1).padStart(2, "0")}</span>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: HEALTH_DOT[e.health] }} />
              <span style={{ fontFamily: M.mono, fontSize: 15, fontWeight: 700 }}>{e.id}</span>
              {e.health !== "healthy" && (
                <span style={{
                  fontSize: 9.5, fontWeight: 700, fontFamily: M.mono, padding: "1px 7px", borderRadius: 4,
                  color: e.health === "crit" ? M.high : M.med,
                  background: e.health === "crit" ? M.highBg : M.medBg,
                }}>{e.health === "crit" ? "需介入" : "關注"}</span>
              )}
              <span style={{ flex: 1 }} />
              <span style={{ fontSize: 12, fontWeight: 700, color: "var(--p, #1E5A44)" }}>檢視 ›</span>
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 6 }}>
              <span style={{ fontFamily: M.mono, fontSize: 19, fontWeight: 700, color: e.health === "crit" ? M.high : e.health === "warn" ? M.med : M.ink }}>
                {e.ooc.toFixed(1)}%
              </span>
              <span style={{ fontFamily: M.mono, fontSize: 11.5, color: M.sub }}>{e.ooc_count} OOC</span>
              <span style={{ flex: 1 }} />
              {(worse || better) && (
                <span style={{ fontFamily: M.mono, fontSize: 11, fontWeight: 700, color: worse ? M.crit : M.ok }}>
                  {worse ? "▲ worsening" : "▼ improving"}
                </span>
              )}
            </div>
            <HeatStrip hourly={e.hourly ?? []} />
            <div style={{ display: "flex", fontSize: 10, fontFamily: M.mono, color: M.faint }}>
              <span>-24h</span><span style={{ flex: 1 }} /><span>現在</span>
            </div>
            <div style={{ fontFamily: M.mono, fontSize: 11, color: M.sub, marginTop: 5 }}>
              {e.lots24h} LOTs ・ {e.fdc} FDC ・ {e.alarms} alarm
            </div>
          </div>
        );
      })}
      {shown.length === 0 && (
        <div style={{ padding: 20, textAlign: "center", color: M.faint, fontSize: 12.5 }}>此分類目前沒有機台</div>
      )}
    </div>
  );
}

const kpiLabel: React.CSSProperties = { fontSize: 11, color: M.sub, fontWeight: 600 };
const kpiValue: React.CSSProperties = {
  fontFamily: M.mono, fontSize: 21, fontWeight: 700, marginTop: 3, color: M.ink,
};
