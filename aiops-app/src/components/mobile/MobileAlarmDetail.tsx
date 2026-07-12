"use client";

/**
 * 手機 1b 告警戰情・設備詳情 — 返回列＋設備標題＋AI 診斷報告（洋紅左框）＋
 * 告警明細列＋底部常駐「Acknowledge・N」動作條。
 * AI 診斷走既有 briefing SSE（scope=alarm, alarmData=叢集摘要）。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useBriefing } from "@/components/alarms/AlarmDetailLegacy";
import { M, cardStyle, sevTone } from "./tokens";
import type { MobileCluster } from "./MobileAlarms";

interface AlarmRow {
  id: number; equipment_id: string; severity: string; title: string;
  status: string; event_time: string;
}

function fmt(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ${d.getHours() < 12 ? "上午" : "下午"}${String(d.getHours() % 12 || 12).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function MobileAlarmDetail({ cluster, onBack }: {
  cluster: MobileCluster;
  onBack: () => void;
}) {
  const [alarms, setAlarms] = useState<AlarmRow[]>([]);
  const [acking, setAcking] = useState(false);
  const [ackMsg, setAckMsg] = useState("");
  const tone = sevTone(cluster.severity);

  const briefingData = useMemo(() => JSON.stringify({
    equipment_id: cluster.equipment_id,
    severity: cluster.severity,
    title: cluster.title,
    summary: cluster.summary,
    count: cluster.count,
    cause: cluster.cause,
    first_at: cluster.first_at,
    last_at: cluster.last_at,
    trigger_events: cluster.trigger_events ?? [],
  }), [cluster]);
  const diag = useBriefing("alarm", briefingData, `mobile-cluster-${cluster.cluster_id}`);
  useEffect(() => { void diag.refresh(); // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cluster.cluster_id]);

  const loadAlarms = useCallback(() => {
    fetch("/api/admin/alarms?status=active&size=200", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((env) => {
        const d = env?.data ?? env;
        const list: AlarmRow[] = Array.isArray(d) ? d : Array.isArray(d?.items) ? d.items : [];
        const ids = new Set(cluster.alarm_ids ?? []);
        setAlarms(list.filter((a) =>
          ids.size > 0 ? ids.has(a.id) : a.equipment_id === cluster.equipment_id));
      })
      .catch(() => { /* ambient */ });
  }, [cluster]);
  useEffect(() => { loadAlarms(); }, [loadAlarms]);

  const ack = async () => {
    setAcking(true);
    try {
      const r = await fetch("/api/admin/alarms/cluster-ack", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ equipment_id: cluster.equipment_id }),
      });
      const env = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(env?.error?.message || `HTTP ${r.status}`);
      const n = (env?.data ?? env)?.acknowledged ?? "?";
      setAckMsg(`已認領 ${n} 件`);
      loadAlarms();
    } catch (e) {
      setAckMsg(`認領失敗：${e instanceof Error ? e.message : e}`);
    } finally {
      setAcking(false);
    }
  };

  return (
    <div style={{ fontFamily: M.sans, color: M.ink, paddingBottom: 130 }}>
      {/* header */}
      <div style={{
        position: "sticky", top: 0, zIndex: 5, background: M.bg,
        padding: "12px 14px 10px", borderBottom: `1px solid ${M.line}`,
        display: "flex", alignItems: "center", gap: 10,
      }}>
        <button onClick={onBack} style={{
          width: 34, height: 34, borderRadius: "50%", border: `1px solid ${M.line}`,
          background: "#fff", fontSize: 16, cursor: "pointer", color: M.ink,
        }}>‹</button>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontFamily: M.mono, fontSize: 19, fontWeight: 800 }}>{cluster.equipment_id}</span>
            <span style={{
              fontSize: 9.5, fontWeight: 700, fontFamily: M.mono, padding: "1px 7px",
              borderRadius: 4, color: tone.fg, background: tone.bg,
            }}>{tone.label}</span>
          </div>
          <div style={{ fontSize: 11, color: M.faint, fontFamily: M.mono, marginTop: 1 }}>
            {cluster.count} alarms ・ {cluster.open_count} open
          </div>
        </div>
      </div>

      <div style={{ padding: "12px 14px 0" }}>
        {/* 時間範圍 + cause */}
        <div style={{ ...cardStyle, padding: "12px 14px" }}>
          <div style={{ fontFamily: M.mono, fontSize: 13, lineHeight: 1.7 }}>
            {fmt(cluster.first_at)}<br />→ {fmt(cluster.last_at)}
          </div>
          {cluster.cause && (
            <span style={{
              display: "inline-block", marginTop: 8, fontFamily: M.mono, fontSize: 11.5,
              padding: "3px 10px", borderRadius: 6, background: M.highBg, color: M.high,
            }}>cause {cluster.cause}</span>
          )}
        </div>

        {/* AI 診斷報告 */}
        <div style={{ ...cardStyle, marginTop: 10, padding: "12px 14px", borderLeft: `3px solid ${M.ai}` }}>
          <div style={{ fontSize: 13.5, fontWeight: 800 }}>
            <span style={{ color: M.ai }}>✦ AI 診斷報告</span>
            <span style={{ color: M.faint, fontWeight: 400 }}>｜</span>{cluster.equipment_id}
          </div>
          <div style={{ fontFamily: M.mono, fontSize: 10.5, color: M.faint, marginTop: 3 }}>
            {cluster.count} alarms ・ {tone.label} ・ {fmt(cluster.first_at)} → {fmt(cluster.last_at)}
          </div>
          <div style={{ fontSize: 13.5, lineHeight: 1.75, marginTop: 8, whiteSpace: "pre-wrap" }}>
            {diag.text || (diag.loading ? "AI 正在診斷…" : cluster.summary)}
          </div>
        </div>

        {/* alarm 明細 */}
        <div style={{ fontSize: 10.5, fontFamily: M.mono, letterSpacing: ".08em", color: M.faint, margin: "16px 0 8px" }}>
          {alarms.length} ALARMS ・ 點任一筆進入深度診斷
        </div>
        {alarms.map((a) => {
          const at = sevTone(a.severity);
          return (
            <a key={a.id} href={`/alarms/${a.id}`} style={{
              ...cardStyle, padding: "11px 13px", marginBottom: 8, display: "block",
              textDecoration: "none", color: M.ink,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontFamily: M.mono, fontSize: 12.5, fontWeight: 700 }}>#{a.id}</span>
                <span style={{
                  fontSize: 9, fontWeight: 700, fontFamily: M.mono, padding: "1px 6px",
                  borderRadius: 4, color: at.fg, background: at.bg,
                }}>{at.label}</span>
                <span style={{ fontFamily: M.mono, fontSize: 11.5, color: M.sub }}>{a.equipment_id}</span>
                <span style={{ flex: 1 }} />
                <span style={{ fontSize: 11.5, fontWeight: 700, color: M.ai }}>深度診斷 ›</span>
              </div>
              <div style={{ fontSize: 12.5, color: M.sub, marginTop: 5, lineHeight: 1.5 }}>{a.title}</div>
            </a>
          );
        })}
      </div>

      {/* 底部常駐 Acknowledge 動作條 */}
      <div style={{
        position: "fixed", left: 0, right: 0, bottom: 56, zIndex: 6,
        padding: "10px 14px calc(10px + env(safe-area-inset-bottom, 0px))",
        background: "linear-gradient(transparent, rgba(243,241,234,0.92) 30%)",
      }}>
        {ackMsg && (
          <div style={{ textAlign: "center", fontSize: 12, color: M.sub, marginBottom: 6 }}>{ackMsg}</div>
        )}
        <button onClick={() => void ack()} disabled={acking || cluster.open_count === 0} style={{
          width: "100%", padding: "13px 0", borderRadius: 12, border: "none",
          background: "var(--p, #1E5A44)", color: "#fff", fontSize: 15, fontWeight: 800,
          cursor: "pointer", opacity: acking ? 0.6 : 1, boxShadow: M.shadow,
        }}>
          {acking ? "認領中…" : `✓ Acknowledge ・ ${cluster.open_count}`}
        </button>
      </div>
    </div>
  );
}
