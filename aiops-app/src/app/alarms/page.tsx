"use client";

/**
 * Alarm Center V2 — Master-Detail + Accordion layout
 *
 * Layout:
 *   Top: AI Alarm Queue Briefing (1-2 句全局戰況)
 *   Left 40%: Alarm list (Master)
 *   Right 60%: Selected alarm detail (Detail)
 *     - AI Synthesis (LLM 整合所有 DR)
 *     - Trigger Event
 *     - DR Accordions (ALERT expanded, PASS collapsed)
 *
 * UX rules:
 *   - Single scrollbar on detail panel only
 *   - No nested scrollbars
 *   - No modals
 */

import { useEffect, useState, useCallback, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import { RenderMiddleware, ChartListRenderer, type SkillFindings, type OutputSchemaField, type ChartDSL } from "@/components/operations/SkillOutputRenderer";

// ── Types ─────────────────────────────────────────────────────────────────────

type DiagnosticResult = {
  log_id: number;
  skill_id: number | null;
  skill_name: string;
  status: string;
  findings: SkillFindings | null;
  output_schema: OutputSchemaField[] | null;
  charts: ChartDSL[] | null;
};

type Alarm = {
  id: number;
  skill_id: number;
  trigger_event: string;
  equipment_id: string;
  lot_id: string;
  step: string | null;
  event_time: string | null;
  severity: string;
  title: string;
  summary: string | null;
  status: string;
  created_at: string;
  findings: SkillFindings | null;
  output_schema: OutputSchemaField[] | null;
  charts?: ChartDSL[] | null;
  diagnostic_results?: DiagnosticResult[];
};

// ── Styles ─────────────────────────────────────────────────────────────────────

const SEV_COLOR: Record<string, string> = {
  CRITICAL: "#dc2626", HIGH: "#f5222d", MEDIUM: "#fa8c16", LOW: "#52c41a",
};

function timeAgo(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

// ── SSE Briefing fetcher ──────────────────────────────────────────────────────

function useBriefing(scope: string, data?: string) {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);

  const fetch_ = useCallback(async () => {
    setLoading(true);
    setText("");
    try {
      // For alarm scopes, use POST to send large JSON body
      const isAlarmScope = scope === "alarm" || scope === "alarm_detail";
      let res: Response;
      if (isAlarmScope && data) {
        res = await fetch("/api/admin/briefing", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ scope, alarmData: JSON.parse(data) }),
        });
      } else {
        const params = new URLSearchParams({ scope });
        res = await fetch(`/api/admin/briefing?${params}`);
      }
      const reader = res.body?.getReader();
      if (!reader) return;
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          // Accept both "data: {...}" (Python sse-starlette) and "data:{...}"
          // (Spring SseEmitter) — SSE spec allows either; the optional space
          // must be trimmed by the client.
          if (!line.startsWith("data:")) continue;
          const payload = line.slice(5).replace(/^\s/, "");
          try {
            const ev = JSON.parse(payload);
            if (ev.type === "chunk") setText(prev => prev + ev.text);
          } catch { /* skip */ }
        }
      }
    } catch { setText("⚠️ 簡報載入失敗"); }
    finally { setLoading(false); }
  }, [scope, data]);

  return { text, loading, refresh: fetch_ };
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function AlarmCenterPage() {
  const [alarms, setAlarms] = useState<Alarm[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("active");
  const [loading, setLoading] = useState(false);

  // Fetch alarms
  const loadAlarms = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`/api/admin/alarms?status=${statusFilter}&days=7&limit=100`);
      const d = await r.json();
      // Handle both {data:[...]} (StandardResponse) and raw array
      const list = Array.isArray(d) ? d : (d?.data ?? []);
      setAlarms(list);
    } catch { setAlarms([]); }
    finally { setLoading(false); }
  }, [statusFilter]);

  useEffect(() => { loadAlarms(); }, [loadAlarms]);

  const selected = useMemo(() => alarms.find(a => a.id === selectedId), [alarms, selectedId]);

  // Auto-select first alarm
  useEffect(() => {
    if (alarms.length > 0 && !selectedId) setSelectedId(alarms[0].id);
  }, [alarms, selectedId]);

  // Stats for briefing
  const stats = useMemo(() => {
    const s: Record<string, number> = {};
    const byTool: Record<string, number> = {};
    for (const a of alarms) {
      s[a.severity] = (s[a.severity] ?? 0) + 1;
      byTool[a.equipment_id] = (byTool[a.equipment_id] ?? 0) + 1;
    }
    const topTools = Object.entries(byTool).sort(([, a], [, b]) => b - a).slice(0, 3);
    return { severities: s, topTools, total: alarms.length };
  }, [alarms]);

  const briefingData = JSON.stringify({
    total: stats.total,
    severities: stats.severities,
    top_equipment: stats.topTools.map(([id, n]) => ({ equipment_id: id, count: n })),
  });

  const queueBriefing = useBriefing("alarm", briefingData);

  // Trigger queue briefing on alarm load
  useEffect(() => { if (alarms.length > 0) queueBriefing.refresh(); }, [alarms.length]); // eslint-disable-line

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden" }}>

      {/* ── Top: Alarm Queue Briefing ──────────────────────────── */}
      <div style={{
        background: "#fff", padding: "14px 24px", borderBottom: "1px solid #e0e0e0",
        display: "flex", alignItems: "center", gap: 16, boxShadow: "0 2px 8px rgba(0,0,0,0.05)",
        flexShrink: 0,
      }}>
        <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
          {Object.entries(stats.severities).map(([sev, count]) => (
            <span key={sev} style={{
              padding: "4px 12px", borderRadius: 16, fontWeight: 600, fontSize: 12,
              background: "#f7f8fc",
              color: SEV_COLOR[sev] ?? "#666",
              border: `1px solid #e2e8f0`,
            }}>
              {sev}: {count}
            </span>
          ))}
        </div>
        <div style={{
          flex: 1, fontSize: 14, color: "#595959",
          borderLeft: "3px solid #1890ff", paddingLeft: 12, lineHeight: 1.5,
        }}>
          {queueBriefing.loading ? (
            <span style={{ color: "#a0aec0" }}>
              <span style={{ display: "inline-block", width: 8, height: 14, background: "#1890ff", animation: "blink 1s step-end infinite", marginRight: 6, verticalAlign: "text-bottom" }} />
              AI 分析告警佇列中...
            </span>
          ) : (
            <span><strong>✨ AI 戰況總結：</strong>{queueBriefing.text || "（等待資料...）"}</span>
          )}
        </div>
        {/* Filter buttons */}
        <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
          {["active", "acknowledged", "all"].map(f => (
            <button key={f} onClick={() => setStatusFilter(f)} style={{
              padding: "4px 12px", fontSize: 12, borderRadius: 4, cursor: "pointer",
              border: statusFilter === f ? "1px solid #1890ff" : "1px solid #d9d9d9",
              background: statusFilter === f ? "#e6f7ff" : "#fff",
              color: statusFilter === f ? "#1890ff" : "#666",
              fontWeight: statusFilter === f ? 600 : 400,
            }}>
              {f === "active" ? "OPEN" : f === "acknowledged" ? "已認領" : "全部"}
            </button>
          ))}
        </div>
      </div>

      {/* ── Content: Master-Detail ─────────────────────────────── */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>

        {/* Master — Alarm List (compact sidebar) */}
        <div style={{ width: 220, flexShrink: 0, background: "#fff", borderRight: "1px solid #e0e0e0", overflowY: "auto" }}>
          {loading && <div style={{ padding: 8, color: "#a0aec0", fontSize: 11 }}>載入中...</div>}
          {alarms.map(a => (
            <div key={a.id} onClick={() => setSelectedId(a.id)} style={{
              padding: "6px 10px", borderBottom: "1px solid #f0f0f0", cursor: "pointer",
              background: selectedId === a.id ? "#e6f7ff" : "transparent",
              borderLeft: selectedId === a.id ? "3px solid #1890ff" : "3px solid transparent",
              transition: "background 0.15s",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2, fontSize: 10 }}>
                <span style={{ color: SEV_COLOR[a.severity] ?? "#666", fontWeight: 700 }}>● {a.severity}</span>
                <span style={{ color: "#bbb", fontSize: 10 }}>{timeAgo(a.created_at)}</span>
              </div>
              <div style={{ fontWeight: 600, fontSize: 11, lineHeight: 1.35, marginBottom: 2, color: "#262626",
                overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" as const }}>
                {a.title}
              </div>
              <div style={{ color: "#aaa", fontSize: 10 }}>
                {a.equipment_id} | {a.status === "active" ? "OPEN" : a.status}
              </div>
            </div>
          ))}
          {alarms.length === 0 && !loading && (
            <div style={{ padding: 40, textAlign: "center", color: "#a0aec0" }}>
              <div style={{ fontSize: 32, marginBottom: 8 }}>✅</div>
              <div style={{ fontSize: 14 }}>目前沒有告警</div>
            </div>
          )}
        </div>

        {/* Detail — Selected Alarm */}
        <div style={{ flex: 1, background: "#f9f9f9", overflowY: "auto", padding: "var(--sp-xl)" }}>
          {selected ? (
            <AlarmDetail alarm={selected} />
          ) : (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "#a0aec0" }}>
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: 40, marginBottom: 8 }}>📋</div>
                <div style={{ fontSize: 14 }}>點擊左側告警查看詳細內容</div>
              </div>
            </div>
          )}
        </div>
      </div>

      <style>{`@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }`}</style>
    </div>
  );
}

// ── Alarm Detail Panel ────────────────────────────────────────────────────────

function AlarmDetail({ alarm }: { alarm: Alarm }) {
  const drs = alarm.diagnostic_results ?? [];

  const [detailTab, setDetailTab] = useState<"trigger" | "evidence">("trigger");

  // Prepare synthesis data — include full DR findings so LLM has real content
  const synthesisData = useMemo(() => JSON.stringify({
    alarm_title: alarm.title,
    equipment_id: alarm.equipment_id,
    severity: alarm.severity,
    trigger_summary: alarm.findings?.summary ?? "",
    trigger_condition_met: alarm.findings?.condition_met,
    diagnostic_rules: drs.map(dr => ({
      name: dr.skill_name,
      status: dr.status,
      condition_met: dr.findings?.condition_met,
      summary: dr.findings?.summary ?? "",
      outputs_keys: Object.keys(dr.findings?.outputs ?? {}),
    })),
    total_dr_count: drs.length,
    alert_dr_count: drs.filter(dr => dr.findings?.condition_met).length,
    pass_dr_count: drs.filter(dr => !dr.findings?.condition_met).length,
  }), [alarm, drs]);

  const synthesis = useBriefing("alarm_detail", synthesisData);
  useEffect(() => { synthesis.refresh(); }, [alarm.id]); // eslint-disable-line

  return (
    <div>
      <h2 style={{ margin: "0 0 4px 0", fontSize: 18, color: "#262626" }}>
        AI 診斷報告 | {alarm.equipment_id}
      </h2>
      <p style={{ color: "#999", marginBottom: 24, fontSize: 13 }}>
        {alarm.title} • {timeAgo(alarm.created_at)}
      </p>

      {/* AI Synthesis — clean style */}
      <div style={{
        background: "#fff",
        border: "1px solid #e2e8f0", borderLeft: "4px solid #4299e1",
        borderRadius: 8, padding: "16px 20px", marginBottom: 16,
      }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#595959", marginBottom: 8, display: "flex", alignItems: "center", gap: 8 }}>
          ✨ AI 綜合診斷 (Synthesis)
        </div>
        <div style={{ fontSize: 14, lineHeight: 1.6, color: "#262626" }}>
          {synthesis.loading ? (
            <span style={{ color: "#a0aec0" }}>
              <span style={{ display: "inline-block", width: 8, height: 14, background: "#1890ff", animation: "blink 1s step-end infinite", marginRight: 6, verticalAlign: "text-bottom" }} />
              AI 正在整合分析結果...
            </span>
          ) : synthesis.text ? (
            <ReactMarkdown>{synthesis.text}</ReactMarkdown>
          ) : (
            <span style={{ color: "#a0aec0" }}>（無診斷結果）</span>
          )}
        </div>
      </div>

      {/* Tabs: Trigger Event | Evidence */}
      <div style={{ display: "flex", borderBottom: "1px solid #e0e0e0", marginBottom: 16 }}>
        {([["trigger", "🔴 觸發原因"], ["evidence", `📊 深度診斷 (${drs.length})`]] as const).map(([key, label]) => (
          <button key={key} onClick={() => setDetailTab(key as "trigger" | "evidence")} style={{
            padding: "10px 20px", fontSize: 13, fontWeight: detailTab === key ? 700 : 400,
            color: detailTab === key ? "#1890ff" : "#666", cursor: "pointer",
            borderBottom: detailTab === key ? "2px solid #1890ff" : "2px solid transparent",
            background: "transparent", border: "none", transition: "0.15s",
          }}>
            {label}
          </button>
        ))}
      </div>

      {detailTab === "trigger" && (
        <div style={{ background: "#fff", border: "1px solid #e0e0e0", borderRadius: 8, padding: 20 }}>
          {alarm.findings ? (
            <div>
              <div style={{
                background: "#fff",
                padding: 12, borderRadius: 4, marginBottom: 12,
                color: "#2d3748",
                border: "1px solid #e2e8f0",
                borderLeft: `4px solid ${alarm.findings.condition_met ? "#e53e3e" : "#48bb78"}`,
                fontSize: 13,
              }}>
                {alarm.findings.summary || (alarm.findings.condition_met ? "條件達成" : "條件未達成")}
              </div>
              <RenderMiddleware
                findings={alarm.findings}
                outputSchema={alarm.output_schema ?? []}
                charts={alarm.charts ?? null}
              />
            </div>
          ) : (
            <div style={{ color: "#a0aec0", fontSize: 13 }}>（無觸發資料）</div>
          )}
        </div>
      )}

      {detailTab === "evidence" && drs.length > 0 && (
        <div>
          {drs.map((dr, idx) => (
            <DRAccordion key={dr.log_id} dr={dr} index={idx} total={drs.length} />
          ))}
        </div>
      )}
      {detailTab === "evidence" && drs.length === 0 && (
        <div style={{ padding: 24, textAlign: "center", color: "#a0aec0" }}>（無深度診斷結果）</div>
      )}
    </div>
  );
}

// ── DR Accordion ──────────────────────────────────────────────────────────────

function DRAccordion({ dr, index, total }: { dr: DiagnosticResult; index: number; total: number }) {
  const isAlert = dr.findings?.condition_met === true;
  const [open, setOpen] = useState(isAlert); // ALERT default open, PASS default closed

  return (
    <div style={{
      border: "1px solid #e0e0e0", borderRadius: 6, marginBottom: 12,
      overflow: "hidden", background: "#fff",
    }}>
      {/* Header */}
      <div onClick={() => setOpen(o => !o)} style={{
        padding: 16, cursor: "pointer",
        display: "flex", justifyContent: "space-between", alignItems: "center",
        fontWeight: 600, fontSize: 14, transition: "background 0.15s",
        background: "#fafafa",
        borderLeft: isAlert ? "4px solid #e53e3e" : "4px solid #48bb78",
        borderBottom: open ? "1px solid #e0e0e0" : "none",
      }}>
        <span>DR {index + 1}/{total}：{dr.skill_name || `Rule #${dr.skill_id}`}</span>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{
            padding: "2px 8px", borderRadius: 4, fontSize: 12, fontWeight: 700, color: "#fff",
            background: isAlert ? "#f5222d" : "#52c41a",
          }}>
            {isAlert ? "ALERT" : "PASS"}
          </span>
          <span style={{ color: "#999", fontSize: 12 }}>{open ? "▼" : "▶"}</span>
        </div>
      </div>

      {/* Body */}
      {open && (
        <div style={{ padding: 16 }}>
          {dr.findings?.summary && (
            <div style={{ fontSize: 13, color: "#595959", marginBottom: 12, lineHeight: 1.5 }}>
              {dr.findings.summary}
            </div>
          )}
          {dr.findings && (
            <RenderMiddleware
              findings={dr.findings}
              outputSchema={dr.output_schema ?? []}
              charts={dr.charts ?? null}
            />
          )}
        </div>
      )}
    </div>
  );
}
