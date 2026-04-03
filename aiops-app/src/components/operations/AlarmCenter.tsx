"use client";

import { useEffect, useState, useCallback } from "react";
import { RenderMiddleware, type SkillFindings, type OutputSchemaField } from "./SkillOutputRenderer";

type Alarm = {
  id: number;
  skill_id: number;
  trigger_event: string;
  equipment_id: string;
  lot_id: string;
  step: string | null;
  event_time: string | null;
  severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  title: string;
  summary: string | null;
  status: "active" | "acknowledged" | "resolved";
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  resolved_at: string | null;
  created_at: string;
  execution_log_id: number | null;
  diagnostic_log_id: number | null;
  findings: SkillFindings | null;
  output_schema: OutputSchemaField[] | null;
  diagnostic_findings: SkillFindings | null;
  diagnostic_output_schema: OutputSchemaField[] | null;
};

// ── Severity config ────────────────────────────────────────────────────────────

const SEV: Record<string, { bg: string; color: string; dot: string; label: string }> = {
  CRITICAL: { bg: "#fef2f2", color: "#dc2626", dot: "#dc2626", label: "CRITICAL" },
  HIGH:     { bg: "#fff7ed", color: "#ea580c", dot: "#ea580c", label: "HIGH" },
  MEDIUM:   { bg: "#fefce8", color: "#ca8a04", dot: "#ca8a04", label: "MEDIUM" },
  LOW:      { bg: "#f0fdf4", color: "#16a34a", dot: "#16a34a", label: "LOW" },
};

// ── Helpers ────────────────────────────────────────────────────────────────────

function timeAgo(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60)    return `${Math.floor(diff)}s ago`;
  if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function parseSummary(raw: string | null): Record<string, unknown> | null {
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function SeverityBadge({ sev }: { sev: string }) {
  const cfg = SEV[sev] ?? SEV.MEDIUM;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "2px 8px", borderRadius: 12,
      background: cfg.bg, color: cfg.color,
      fontSize: 11, fontWeight: 700, letterSpacing: "0.3px",
    }}>
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: cfg.dot, flexShrink: 0 }} />
      {cfg.label}
    </span>
  );
}

function StatusChip({ status }: { status: string }) {
  const map: Record<string, { bg: string; color: string; label: string }> = {
    active:       { bg: "#fff5f5", color: "#c53030", label: "OPEN" },
    acknowledged: { bg: "#ebf8ff", color: "#2b6cb0", label: "已認領" },
    resolved:     { bg: "#f0fff4", color: "#276749", label: "已解決" },
  };
  const cfg = map[status] ?? map.active;
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 10,
      background: cfg.bg, color: cfg.color,
      fontSize: 11, fontWeight: 600,
    }}>
      {cfg.label}
    </span>
  );
}

function FindingsPanel({ alarm }: { alarm: Alarm }) {
  const hasApFindings = alarm.findings && Object.keys(alarm.findings).length > 0;
  const hasDrFindings = alarm.diagnostic_findings && Object.keys(alarm.diagnostic_findings).length > 0;
  const parsed = parseSummary(alarm.summary);

  return (
    <div style={{ padding: "12px 16px", background: "#f8fafc", borderTop: "1px solid #e2e8f0" }}>

      {/* Layer 1: Auto-Patrol trigger findings */}
      <div style={{ marginBottom: hasDrFindings || alarm.diagnostic_log_id ? 16 : 10 }}>
        <div style={{
          fontSize: 11, fontWeight: 700, color: "#718096", marginBottom: 8,
          textTransform: "uppercase", letterSpacing: "0.4px",
          display: "flex", alignItems: "center", gap: 6,
        }}>
          <span style={{ background: "#e2e8f0", borderRadius: 4, padding: "1px 6px" }}>1</span>
          觸發原因（Auto-Patrol）
        </div>
        {hasApFindings ? (
          <RenderMiddleware findings={alarm.findings!} outputSchema={alarm.output_schema ?? []} />
        ) : parsed && Object.keys(parsed).length > 0 ? (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {Object.entries(parsed).map(([k, v]) => (
              <div key={k} style={{
                background: "#fff", border: "1px solid #e2e8f0", borderRadius: 6,
                padding: "4px 10px", fontSize: 12,
              }}>
                <span style={{ color: "#718096" }}>{k}: </span>
                <span style={{ fontWeight: 600, color: "#2d3748" }}>
                  {typeof v === "object" ? JSON.stringify(v) : String(v)}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ fontSize: 12, color: "#a0aec0" }}>{alarm.summary || "無觸發資料"}</div>
        )}
      </div>

      {/* Layer 2: Diagnostic Rule findings */}
      {hasDrFindings && (
        <div style={{ borderTop: "2px dashed #bee3f8", paddingTop: 14, marginBottom: 10 }}>
          <div style={{
            fontSize: 11, fontWeight: 700, color: "#2b6cb0", marginBottom: 8,
            textTransform: "uppercase", letterSpacing: "0.4px",
            display: "flex", alignItems: "center", gap: 6,
          }}>
            <span style={{ background: "#ebf8ff", color: "#2b6cb0", borderRadius: 4, padding: "1px 6px" }}>2</span>
            深度診斷結果（Diagnostic Rule）
          </div>
          <RenderMiddleware
            findings={alarm.diagnostic_findings!}
            outputSchema={alarm.diagnostic_output_schema ?? []}
          />
        </div>
      )}

      {!hasDrFindings && alarm.diagnostic_log_id && (
        <div style={{ fontSize: 11, color: "#a0aec0", marginBottom: 10, borderTop: "1px dashed #e2e8f0", paddingTop: 10 }}>
          🔄 診斷規則已觸發，等待結果...
        </div>
      )}

      <a
        href="/admin/skills"
        target="_blank"
        rel="noreferrer"
        style={{
          display: "inline-flex", alignItems: "center", gap: 4,
          padding: "5px 12px", borderRadius: 6,
          background: "#ebf4ff", color: "#2b6cb0",
          fontSize: 12, fontWeight: 600, textDecoration: "none",
        }}
      >
        🔬 前往 Diagnostic Rules
      </a>
    </div>
  );
}

// ── AlarmRow ───────────────────────────────────────────────────────────────────

function AlarmRow({
  alarm,
  expanded,
  onToggle,
  onAck,
  onResolve,
}: {
  alarm: Alarm;
  expanded: boolean;
  onToggle: () => void;
  onAck: (id: number) => void;
  onResolve: (id: number) => void;
}) {
  const sev = SEV[alarm.severity] ?? SEV.MEDIUM;

  return (
    <div style={{ borderBottom: "1px solid #e2e8f0" }}>
      {/* Main row */}
      <div
        onClick={onToggle}
        style={{
          display: "grid",
          gridTemplateColumns: "90px 1fr 100px 80px 90px 140px",
          alignItems: "center",
          gap: 8,
          padding: "10px 16px",
          cursor: "pointer",
          background: expanded ? sev.bg : "#fff",
          transition: "background 0.1s",
        }}
      >
        <SeverityBadge sev={alarm.severity} />

        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 13, color: "#1a202c", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {alarm.title}
          </div>
          <div style={{ fontSize: 11, color: "#a0aec0", marginTop: 1 }}>{alarm.trigger_event}</div>
        </div>

        <div style={{ fontSize: 12, color: "#4a5568", fontWeight: 500 }}>
          {alarm.equipment_id || "—"}
        </div>

        <div style={{ fontSize: 11, color: "#a0aec0" }}>{timeAgo(alarm.created_at)}</div>

        <StatusChip status={alarm.status} />

        {/* Actions */}
        <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }} onClick={e => e.stopPropagation()}>
          {alarm.status === "active" && (
            <button
              onClick={() => onAck(alarm.id)}
              style={{
                padding: "3px 10px", borderRadius: 5, border: "1px solid #bee3f8",
                background: "#ebf8ff", color: "#2b6cb0",
                fontSize: 11, fontWeight: 600, cursor: "pointer",
              }}
            >
              認領
            </button>
          )}
          {alarm.status !== "resolved" && (
            <button
              onClick={() => onResolve(alarm.id)}
              style={{
                padding: "3px 10px", borderRadius: 5, border: "1px solid #c6f6d5",
                background: "#f0fff4", color: "#276749",
                fontSize: 11, fontWeight: 600, cursor: "pointer",
              }}
            >
              解決
            </button>
          )}
        </div>
      </div>

      {/* Expand panel */}
      {expanded && (
        <FindingsPanel alarm={alarm} />
      )}
    </div>
  );
}

// ── Main AlarmCenter ───────────────────────────────────────────────────────────

const STATUS_TABS = [
  { key: "active",       label: "OPEN" },
  { key: "acknowledged", label: "已認領" },
  { key: "all",          label: "全部" },
];

const SEV_OPTS = ["全部", "CRITICAL", "HIGH", "MEDIUM", "LOW"];

export function AlarmCenter() {
  const [alarms, setAlarms]         = useState<Alarm[]>([]);
  const [loading, setLoading]       = useState(true);
  const [statusTab, setStatusTab]   = useState<string>("active");
  const [sevFilter, setSevFilter]   = useState("全部");
  const [eqFilter, setEqFilter]     = useState("");
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [counts, setCounts]         = useState<Record<string, number>>({ active: 0, acknowledged: 0 });

  const fetchAlarms = useCallback(async () => {
    const params = new URLSearchParams({ status: statusTab, limit: "100" });
    if (sevFilter !== "全部") params.set("severity", sevFilter);
    if (eqFilter.trim()) params.set("equipment_id", eqFilter.trim());

    const res = await fetch(`/api/admin/alarms?${params}`);
    if (!res.ok) return;
    const data: Alarm[] = await res.json();
    setAlarms(data);
    setLoading(false);
  }, [statusTab, sevFilter, eqFilter]);

  // Fetch counts for tab badges
  const fetchCounts = useCallback(async () => {
    const [activeRes, ackedRes] = await Promise.all([
      fetch("/api/admin/alarms?status=active&limit=1"),
      fetch("/api/admin/alarms?status=acknowledged&limit=1"),
    ]);
    // counts are approximate via stats endpoint
    const statsRes = await fetch("/api/admin/alarms/stats");
    if (statsRes.ok) {
      const stats = await statsRes.json();
      setCounts({
        active: stats.total_active ?? 0,
        acknowledged: 0, // not in stats, just show total_active
      });
    }
  }, []);

  useEffect(() => { fetchAlarms(); }, [fetchAlarms]);
  useEffect(() => { fetchCounts(); }, [fetchCounts]);

  // Poll every 15s
  useEffect(() => {
    const id = setInterval(() => { fetchAlarms(); fetchCounts(); }, 15000);
    return () => clearInterval(id);
  }, [fetchAlarms, fetchCounts]);

  async function handleAck(id: number) {
    await fetch(`/api/admin/alarms/${id}/acknowledge`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ acknowledged_by: "operator" }),
    });
    fetchAlarms();
    fetchCounts();
  }

  async function handleResolve(id: number) {
    await fetch(`/api/admin/alarms/${id}/resolve`, { method: "PATCH" });
    fetchAlarms();
    fetchCounts();
  }

  // Summary bar counts by severity (from current list)
  const critCount = alarms.filter(a => a.severity === "CRITICAL").length;
  const highCount = alarms.filter(a => a.severity === "HIGH").length;
  const medCount  = alarms.filter(a => a.severity === "MEDIUM").length;
  const lowCount  = alarms.filter(a => a.severity === "LOW").length;

  return (
    <div style={{ padding: "20px 24px" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "#1a202c" }}>🔔 告警中心</h2>
          <p style={{ margin: "2px 0 0", fontSize: 12, color: "#a0aec0" }}>每 15 秒自動更新</p>
        </div>

        {/* Severity summary pills */}
        <div style={{ display: "flex", gap: 8 }}>
          {(
            [
              { key: "CRITICAL", count: critCount },
              { key: "HIGH",     count: highCount },
              { key: "MEDIUM",   count: medCount  },
              { key: "LOW",      count: lowCount  },
            ] as { key: keyof typeof SEV; count: number }[]
          ).map(({ key, count }) => {
            const { bg, color, label } = SEV[key];
            return (
            <div key={label} style={{
              padding: "4px 12px", borderRadius: 16,
              background: count > 0 ? bg : "#f7fafc",
              color: count > 0 ? color : "#a0aec0",
              fontSize: 12, fontWeight: 700,
              border: `1px solid ${count > 0 ? color + "33" : "#e2e8f0"}`,
            }}>
              {label}: {count}
            </div>
            );
          })}
        </div>
      </div>

      {/* Status tabs + filters */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12, gap: 12 }}>
        {/* Status tabs */}
        <div style={{ display: "flex", gap: 2, background: "#f7fafc", borderRadius: 8, padding: 3 }}>
          {STATUS_TABS.map(t => (
            <button
              key={t.key}
              onClick={() => { setStatusTab(t.key); setExpandedId(null); }}
              style={{
                padding: "5px 14px", borderRadius: 6, border: "none", cursor: "pointer",
                background: statusTab === t.key ? "#fff" : "transparent",
                color: statusTab === t.key ? "#2b6cb0" : "#718096",
                fontWeight: statusTab === t.key ? 700 : 400,
                fontSize: 13,
                boxShadow: statusTab === t.key ? "0 1px 3px rgba(0,0,0,0.1)" : "none",
              }}
            >
              {t.label}
              {t.key === "active" && counts.active > 0 && (
                <span style={{
                  marginLeft: 5, background: "#e53e3e", color: "#fff",
                  fontSize: 10, fontWeight: 700, padding: "1px 5px", borderRadius: 8,
                }}>
                  {counts.active}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Filters */}
        <div style={{ display: "flex", gap: 8 }}>
          <select
            value={sevFilter}
            onChange={e => { setSevFilter(e.target.value); setExpandedId(null); }}
            style={{ padding: "5px 10px", borderRadius: 6, border: "1px solid #e2e8f0", fontSize: 12, color: "#4a5568" }}
          >
            {SEV_OPTS.map(s => <option key={s}>{s}</option>)}
          </select>
          <input
            placeholder="設備 ID..."
            value={eqFilter}
            onChange={e => setEqFilter(e.target.value)}
            style={{ padding: "5px 10px", borderRadius: 6, border: "1px solid #e2e8f0", fontSize: 12, width: 120, color: "#4a5568" }}
          />
        </div>
      </div>

      {/* Table header */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "90px 1fr 100px 80px 90px 140px",
        gap: 8,
        padding: "6px 16px",
        background: "#f7fafc",
        borderRadius: "8px 8px 0 0",
        border: "1px solid #e2e8f0",
        borderBottom: "none",
        fontSize: 11, fontWeight: 600, color: "#718096", textTransform: "uppercase", letterSpacing: "0.4px",
      }}>
        <span>嚴重度</span>
        <span>標題</span>
        <span>設備</span>
        <span>時間</span>
        <span>狀態</span>
        <span style={{ textAlign: "right" }}>操作</span>
      </div>

      {/* Alarm list */}
      <div style={{ border: "1px solid #e2e8f0", borderRadius: "0 0 8px 8px", background: "#fff", overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "#a0aec0", fontSize: 13 }}>載入中...</div>
        ) : alarms.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center" }}>
            <div style={{ fontSize: 32, marginBottom: 8 }}>✅</div>
            <div style={{ fontSize: 14, color: "#4a5568", fontWeight: 600 }}>
              {statusTab === "active" ? "目前沒有未處理的告警" : "沒有符合條件的告警"}
            </div>
            <div style={{ fontSize: 12, color: "#a0aec0", marginTop: 4 }}>
              Auto-Patrol 持續監控中...
            </div>
          </div>
        ) : (
          alarms.map(alarm => (
            <AlarmRow
              key={alarm.id}
              alarm={alarm}
              expanded={expandedId === alarm.id}
              onToggle={() => setExpandedId(expandedId === alarm.id ? null : alarm.id)}
              onAck={handleAck}
              onResolve={handleResolve}
            />
          ))
        )}
      </div>

      {alarms.length > 0 && (
        <div style={{ textAlign: "right", fontSize: 11, color: "#a0aec0", marginTop: 6 }}>
          共 {alarms.length} 筆 · 點擊列可展開診斷結果
        </div>
      )}
    </div>
  );
}
