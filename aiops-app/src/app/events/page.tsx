"use client";

import { useState, useEffect, useCallback } from "react";
import { Topbar } from "@/components/layout/Topbar";
import { AICopilot } from "@/components/copilot/AICopilot";
import { AnalysisPanel } from "@/components/layout/AnalysisPanel";
import type { AIOpsReportContract } from "aiops-contract";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface EventItem {
  event_id: string;
  equipment_id: string;
  event_type: string;
  severity: string;
  description: string;
  timestamp: string;
  metadata?: Record<string, unknown>;
}

interface EquipmentItem {
  equipment_id: string;
  name: string;
  status: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const EQUIPMENT_IDS = ["EQP-01","EQP-02","EQP-03","EQP-04","EQP-05",
                       "EQP-06","EQP-07","EQP-08","EQP-09","EQP-10"];

const SEVERITY_COLOR: Record<string, string> = {
  critical: "#e53e3e",
  warning:  "#d69e2e",
  info:     "#718096",
};

const SEVERITY_BG: Record<string, string> = {
  critical: "#fff5f5",
  warning:  "#fffff0",
  info:     "#f7f8fc",
};

const SEVERITY_LABELS = ["全部", "critical", "warning", "info"];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function EventsPage() {
  const [events, setEvents]                 = useState<EventItem[]>([]);
  const [equipment, setEquipment]           = useState<EquipmentItem[]>([]);
  const [loading, setLoading]               = useState(true);
  const [filterEquipment, setFilterEquipment] = useState<string>("全部");
  const [filterSeverity, setFilterSeverity]   = useState<string>("全部");
  const [triggerMessage, setTriggerMessage]   = useState<string | null>(null);
  const [contract, setContract]               = useState<AIOpsReportContract | null>(null);
  const [investigateMode, setInvestigateMode] = useState(false);

  const fetchEquipment = useCallback(async () => {
    try {
      const res = await fetch("/api/ontology/equipment");
      if (res.ok) {
        const data = await res.json();
        setEquipment(data.items ?? []);
      }
    } catch { /* ignore */ }
  }, []);

  const fetchEvents = useCallback(async () => {
    setLoading(true);
    try {
      // Fetch events from all equipment concurrently
      const results = await Promise.allSettled(
        EQUIPMENT_IDS.map((id) =>
          fetch(`/api/ontology/events?equipment_id=${id}&limit=20`).then((r) => r.json())
        )
      );

      const all: EventItem[] = [];
      results.forEach((r) => {
        if (r.status === "fulfilled" && r.value?.items) {
          all.push(...r.value.items);
        }
      });

      // Sort: newest first
      all.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
      setEvents(all.slice(0, 200)); // cap at 200
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    fetchEquipment();
    fetchEvents();
    const timer = setInterval(fetchEvents, 15_000);
    return () => clearInterval(timer);
  }, [fetchEquipment, fetchEvents]);

  // Filtered view
  const filtered = events.filter((e) => {
    if (filterEquipment !== "全部" && e.equipment_id !== filterEquipment) return false;
    if (filterSeverity  !== "全部" && e.severity      !== filterSeverity)  return false;
    return true;
  });

  const criticalCount = events.filter((e) => e.severity === "critical").length;
  const warningCount  = events.filter((e) => e.severity === "warning").length;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: "#f7f8fc", overflow: "hidden" }}>
      <Topbar />

      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {/* Center: Events or Analysis Panel */}
        {investigateMode && (
          <AnalysisPanel
            contract={contract}
            onClose={() => { setInvestigateMode(false); setContract(null); }}
            onAgentMessage={(msg) => setTriggerMessage(msg)}
          />
        )}
        <main style={{ flex: investigateMode ? 0 : 1, overflowY: "auto", padding: 24, minWidth: 0, display: investigateMode ? "none" : undefined }}>
          {/* Header */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
            <div>
              <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "#1a202c" }}>事件紀錄</h2>
              <div style={{ fontSize: 12, color: "#a0aec0", marginTop: 2 }}>
                共 {events.length} 筆 · 每 15 秒更新
              </div>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <div style={{ padding: "4px 12px", background: "#fff5f5", border: "1px solid #fed7d7", borderRadius: 20, fontSize: 12, color: "#c53030", fontWeight: 600 }}>
                ● {criticalCount} Critical
              </div>
              <div style={{ padding: "4px 12px", background: "#fffff0", border: "1px solid #fefcbf", borderRadius: 20, fontSize: 12, color: "#975a16", fontWeight: 600 }}>
                ● {warningCount} Warning
              </div>
            </div>
          </div>

          {/* Filters */}
          <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
            {/* Equipment filter */}
            <div>
              <div style={{ fontSize: 11, color: "#718096", marginBottom: 4, fontWeight: 600 }}>設備</div>
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                {["全部", ...equipment.map((e) => e.equipment_id)].map((id) => (
                  <button
                    key={id}
                    onClick={() => setFilterEquipment(id)}
                    style={{
                      padding: "4px 10px",
                      borderRadius: 12,
                      border: "1px solid",
                      borderColor: filterEquipment === id ? "#2b6cb0" : "#e2e8f0",
                      background: filterEquipment === id ? "#ebf4ff" : "#ffffff",
                      color: filterEquipment === id ? "#2b6cb0" : "#718096",
                      fontSize: 11,
                      fontWeight: filterEquipment === id ? 600 : 400,
                      cursor: "pointer",
                    }}
                  >
                    {id}
                  </button>
                ))}
              </div>
            </div>

            {/* Severity filter */}
            <div>
              <div style={{ fontSize: 11, color: "#718096", marginBottom: 4, fontWeight: 600 }}>嚴重度</div>
              <div style={{ display: "flex", gap: 4 }}>
                {SEVERITY_LABELS.map((sev) => {
                  const color = sev === "全部" ? "#718096" : SEVERITY_COLOR[sev];
                  return (
                    <button
                      key={sev}
                      onClick={() => setFilterSeverity(sev)}
                      style={{
                        padding: "4px 10px",
                        borderRadius: 12,
                        border: "1px solid",
                        borderColor: filterSeverity === sev ? color : "#e2e8f0",
                        background: filterSeverity === sev ? `${color}15` : "#ffffff",
                        color: filterSeverity === sev ? color : "#718096",
                        fontSize: 11,
                        fontWeight: filterSeverity === sev ? 600 : 400,
                        cursor: "pointer",
                        textTransform: "capitalize",
                      }}
                    >
                      {sev}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Event Table */}
          <div style={{ background: "#ffffff", border: "1px solid #e2e8f0", borderRadius: 10, overflow: "hidden" }}>
            {/* Table header */}
            <div style={{
              display: "grid",
              gridTemplateColumns: "100px 90px 1fr 160px 100px",
              padding: "10px 16px",
              background: "#f7f8fc",
              borderBottom: "1px solid #e2e8f0",
              fontSize: 11,
              fontWeight: 600,
              color: "#718096",
              textTransform: "uppercase",
              letterSpacing: "0.5px",
            }}>
              <span>設備</span>
              <span>嚴重度</span>
              <span>描述</span>
              <span>時間</span>
              <span></span>
            </div>

            {loading && (
              <div style={{ padding: 24, textAlign: "center", color: "#a0aec0", fontSize: 13 }}>載入中...</div>
            )}

            {!loading && filtered.length === 0 && (
              <div style={{ padding: 24, textAlign: "center", color: "#a0aec0", fontSize: 13 }}>無符合條件的事件</div>
            )}

            {filtered.map((ev, i) => {
              const color = SEVERITY_COLOR[ev.severity] ?? "#718096";
              const bg    = i % 2 === 0 ? "#ffffff" : "#fafbfc";
              const meta  = ev.metadata as Record<string, unknown> | undefined;
              return (
                <div
                  key={`${ev.event_id}-${i}`}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "100px 90px 1fr 160px 100px",
                    padding: "10px 16px",
                    background: bg,
                    borderBottom: "1px solid #f0f0f0",
                    alignItems: "center",
                    fontSize: 12,
                  }}
                >
                  <span style={{ color: "#2b6cb0", fontWeight: 500, fontFamily: "monospace" }}>
                    {ev.equipment_id}
                  </span>
                  <span>
                    <span style={{
                      padding: "2px 8px",
                      borderRadius: 10,
                      fontSize: 10,
                      fontWeight: 700,
                      background: `${color}20`,
                      color,
                      textTransform: "uppercase",
                    }}>
                      {ev.severity}
                    </span>
                  </span>
                  <span style={{ color: "#1a202c" }}>
                    {ev.description}
                    {meta?.lotID != null && (
                      <span style={{ marginLeft: 8, color: "#a0aec0", fontSize: 11 }}>
                        LOT: {String(meta.lotID)}
                      </span>
                    )}
                  </span>
                  <span style={{ color: "#718096", fontFamily: "monospace", fontSize: 11 }}>
                    {new Date(ev.timestamp).toLocaleString("zh-TW", { hour12: false })}
                  </span>
                  <span>
                    <button
                      onClick={() => setTriggerMessage(
                        `請分析 ${ev.equipment_id} 的 ${ev.event_type} 事件：${ev.description}`
                      )}
                      style={{
                        padding: "4px 10px",
                        background: "#ebf4ff",
                        border: "1px solid #bee3f8",
                        borderRadius: 5,
                        fontSize: 11,
                        color: "#2b6cb0",
                        cursor: "pointer",
                        fontWeight: 500,
                      }}
                    >
                      AI 診斷
                    </button>
                  </span>
                </div>
              );
            })}
          </div>
        </main>

        {/* Right: AI Co-Pilot */}
        <aside style={{ width: 360, flexShrink: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <AICopilot
            triggerMessage={triggerMessage}
            onTriggerConsumed={() => setTriggerMessage(null)}
            onContract={(c) => { setContract(c); setInvestigateMode(true); }}
          />
        </aside>
      </div>
    </div>
  );
}
