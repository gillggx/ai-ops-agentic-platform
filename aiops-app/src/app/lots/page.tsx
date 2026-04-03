"use client";

import { useState, useEffect, useCallback } from "react";
import { Topbar } from "@/components/layout/Topbar";
import { AICopilot } from "@/components/copilot/AICopilot";
import { AnalysisPanel } from "@/components/layout/AnalysisPanel";
import type { AIOpsReportContract } from "aiops-contract";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface LotItem {
  lot_id: string;
  status: string;           // Processing | Waiting | Finished
  current_step?: number;    // step number 1-100
}

interface EventItem {
  event_id: string;
  equipment_id: string;
  event_type: string;
  severity: string;
  description: string;
  timestamp: string;
  metadata?: {
    lotID?: string;
    step?: string;
    spc_status?: string;
  };
}

interface DcObject {
  parameters: Record<string, number>;
  step?: string;
  toolID?: string;
  eventTime?: string;
}

interface SpcObject {
  charts?: Record<string, { value: number; ucl: number; lcl: number }>;
  spc_status?: string;
  step?: string;
  toolID?: string;
  eventTime?: string;
}

interface StepRow {
  step: string;
  toolID: string;
  eventType: string;
  spcStatus: string;
  timestamp: string;
  severity: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STATUS_COLOR: Record<string, { dot: string; bg: string; text: string }> = {
  Processing: { dot: "#38a169", bg: "#f0fff4", text: "#276749" },
  Waiting:    { dot: "#d69e2e", bg: "#fffff0", text: "#975a16" },
  Finished:   { dot: "#a0aec0", bg: "#f7f8fc", text: "#718096" },
};

const SPC_COLOR: Record<string, string> = {
  PASS: "#38a169",
  OOC:  "#e53e3e",
  FAIL: "#e53e3e",
  "":   "#a0aec0",
};

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function LotsPage() {
  const [lots, setLots]                         = useState<LotItem[]>([]);
  const [selectedLot, setSelectedLot]           = useState<LotItem | null>(null);
  const [events, setEvents]                     = useState<EventItem[]>([]);
  const [loadingLots, setLoadingLots]           = useState(true);
  const [loadingEvents, setLoadingEvents]       = useState(false);
  const [expandedStep, setExpandedStep]         = useState<string | null>(null);
  const [stepObjects, setStepObjects]           = useState<{ dc?: DcObject; spc?: SpcObject } | null>(null);
  const [loadingObjects, setLoadingObjects]     = useState(false);
  const [triggerMessage, setTriggerMessage]     = useState<string | null>(null);
  const [contract, setContract]                 = useState<AIOpsReportContract | null>(null);
  const [investigateMode, setInvestigateMode]   = useState(false);

  // ── Fetch lot list ──────────────────────────────────────────────────────

  const fetchLots = useCallback(async () => {
    try {
      const res = await fetch("/api/ontology/lots");
      if (!res.ok) return;
      const data = await res.json() as LotItem[];
      // Sort: Processing first, then Waiting, then Finished
      const order: Record<string, number> = { Processing: 0, Waiting: 1, Finished: 2 };
      data.sort((a, b) => (order[a.status] ?? 3) - (order[b.status] ?? 3));
      setLots(data);
    } finally {
      setLoadingLots(false);
    }
  }, []);

  useEffect(() => {
    fetchLots();
    const t = setInterval(fetchLots, 15_000);
    return () => clearInterval(t);
  }, [fetchLots]);

  // ── Fetch events for selected lot ──────────────────────────────────────

  const fetchLotEvents = useCallback(async (lotId: string) => {
    setLoadingEvents(true);
    setEvents([]);
    setExpandedStep(null);
    setStepObjects(null);
    try {
      const res = await fetch(`/api/ontology/events?lot_id=${lotId}&limit=200`);
      if (!res.ok) return;
      const data = await res.json();
      const items: EventItem[] = data.items ?? [];
      // Sort oldest first for timeline
      items.sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
      setEvents(items);
    } finally {
      setLoadingEvents(false);
    }
  }, []);

  useEffect(() => {
    if (selectedLot) fetchLotEvents(selectedLot.lot_id);
  }, [selectedLot, fetchLotEvents]);

  // ── Fetch DC + SPC objects for a step ──────────────────────────────────

  const fetchStepObjects = useCallback(async (lotId: string, step: string) => {
    setLoadingObjects(true);
    setStepObjects(null);
    try {
      const [dcRes, spcRes] = await Promise.allSettled([
        fetch(`/api/ontology/lots/${lotId}/objects?objectName=DC&step=${encodeURIComponent(step)}`).then((r) => r.json()),
        fetch(`/api/ontology/lots/${lotId}/objects?objectName=SPC&step=${encodeURIComponent(step)}`).then((r) => r.json()),
      ]);
      const dc  = dcRes.status  === "fulfilled" ? (dcRes.value.data?.[0]  as DcObject  | undefined) : undefined;
      const spc = spcRes.status === "fulfilled" ? (spcRes.value.data?.[0] as SpcObject | undefined) : undefined;
      setStepObjects({ dc, spc });
    } finally {
      setLoadingObjects(false);
    }
  }, []);

  const handleStepClick = (step: string) => {
    if (expandedStep === step) {
      setExpandedStep(null);
      setStepObjects(null);
      return;
    }
    setExpandedStep(step);
    if (selectedLot) fetchStepObjects(selectedLot.lot_id, step);
  };

  // ── Derive timeline rows from events ───────────────────────────────────

  const timelineRows: StepRow[] = (() => {
    const seen = new Map<string, StepRow>();
    for (const ev of events) {
      const step = ev.metadata?.step ?? "";
      if (!step) continue;
      const key = `${ev.equipment_id}::${step}`;
      const spcStatus = ev.metadata?.spc_status ?? "";
      // Keep last event per (tool, step); escalate severity
      const existing = seen.get(key);
      if (!existing || new Date(ev.timestamp) > new Date(existing.timestamp)) {
        seen.set(key, {
          step,
          toolID:    ev.equipment_id,
          eventType: ev.event_type,
          spcStatus,
          timestamp: ev.timestamp,
          severity:  ev.severity,
        });
      }
    }
    return Array.from(seen.values());
  })();

  const processingCount = lots.filter((l) => l.status === "Processing").length;
  const waitingCount    = lots.filter((l) => l.status === "Waiting").length;

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: "#f7f8fc", overflow: "hidden" }}>
      <Topbar />

      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>

        {/* ── Left: Lot List ── */}
        <aside style={{
          width: 220,
          flexShrink: 0,
          background: "#ffffff",
          borderRight: "1px solid #e2e8f0",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}>
          {/* header */}
          <div style={{ padding: "14px 16px", borderBottom: "1px solid #e2e8f0" }}>
            <div style={{ fontWeight: 700, fontSize: 14, color: "#1a202c" }}>Lot Tracker</div>
            <div style={{ fontSize: 11, color: "#a0aec0", marginTop: 2 }}>
              {processingCount} 執行中 · {waitingCount} 等待
            </div>
          </div>

          {/* lot list */}
          <div style={{ flex: 1, overflowY: "auto", padding: "8px 8px" }}>
            {loadingLots && (
              <div style={{ padding: 16, textAlign: "center", color: "#a0aec0", fontSize: 12 }}>載入中...</div>
            )}
            {lots.map((lot) => {
              const c = STATUS_COLOR[lot.status] ?? STATUS_COLOR["Waiting"];
              const active = selectedLot?.lot_id === lot.lot_id;
              return (
                <button
                  key={lot.lot_id}
                  onClick={() => setSelectedLot(lot)}
                  style={{
                    display: "block",
                    width: "100%",
                    textAlign: "left",
                    padding: "9px 12px",
                    borderRadius: 6,
                    border: active ? "1px solid #bee3f8" : "1px solid transparent",
                    background: active ? "#ebf4ff" : "transparent",
                    cursor: "pointer",
                    marginBottom: 2,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 3 }}>
                    <span style={{ width: 7, height: 7, borderRadius: "50%", background: c.dot, flexShrink: 0, display: "inline-block" }} />
                    <span style={{ fontFamily: "monospace", fontSize: 12, fontWeight: 600, color: active ? "#2b6cb0" : "#1a202c" }}>
                      {lot.lot_id}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 6, paddingLeft: 13 }}>
                    <span style={{
                      fontSize: 10,
                      fontWeight: 600,
                      padding: "1px 6px",
                      borderRadius: 8,
                      background: c.bg,
                      color: c.text,
                      border: `1px solid ${c.dot}30`,
                    }}>
                      {lot.status}
                    </span>
                    {lot.current_step != null && (
                      <span style={{ fontSize: 10, color: "#a0aec0" }}>Step {lot.current_step}</span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </aside>

        {/* ── Center: Journey Timeline or Analysis Panel ── */}
        {investigateMode && (
          <AnalysisPanel
            contract={contract}
            onClose={() => { setInvestigateMode(false); setContract(null); }}
            onAgentMessage={(msg) => setTriggerMessage(msg)}
          />
        )}
        <main style={{ flex: investigateMode ? 0 : 1, overflowY: "auto", padding: 24, minWidth: 0, display: investigateMode ? "none" : undefined }}>
          {!selectedLot ? (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "60%", color: "#a0aec0", fontSize: 13 }}>
              ← 請從左側選擇一個 Lot
            </div>
          ) : (
            <>
              {/* Lot header */}
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
                <div>
                  <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "#1a202c", fontFamily: "monospace" }}>
                    {selectedLot.lot_id}
                  </h2>
                  <div style={{ fontSize: 12, color: "#718096", marginTop: 2 }}>
                    {timelineRows.length} 個製程步驟記錄
                    {selectedLot.current_step != null && ` · 目前 Step ${selectedLot.current_step}`}
                  </div>
                </div>
                <div style={{ marginLeft: "auto" }}>
                  <button
                    onClick={() => setTriggerMessage(
                      `請分析 lot ${selectedLot.lot_id} 的製程歷程。目前狀態: ${selectedLot.status}，已記錄 ${timelineRows.length} 個步驟。請找出任何異常或需要關注的地方。`
                    )}
                    style={{
                      padding: "6px 14px",
                      background: "#ebf4ff",
                      border: "1px solid #bee3f8",
                      borderRadius: 6,
                      fontSize: 12,
                      color: "#2b6cb0",
                      cursor: "pointer",
                      fontWeight: 500,
                    }}
                  >
                    AI 全程分析
                  </button>
                </div>
              </div>

              {loadingEvents && (
                <div style={{ padding: 24, textAlign: "center", color: "#a0aec0", fontSize: 13 }}>載入製程記錄...</div>
              )}

              {!loadingEvents && timelineRows.length === 0 && (
                <div style={{ padding: 24, textAlign: "center", color: "#a0aec0", fontSize: 13, background: "#fff", borderRadius: 10, border: "1px solid #e2e8f0" }}>
                  此 Lot 尚無製程記錄
                </div>
              )}

              {/* Timeline */}
              {timelineRows.map((row, idx) => {
                const spcColor  = SPC_COLOR[row.spcStatus] ?? SPC_COLOR[""];
                const isExpanded = expandedStep === `${row.toolID}::${row.step}`;
                const hasOoc     = row.spcStatus === "OOC" || row.spcStatus === "FAIL";

                return (
                  <div key={`${row.toolID}-${row.step}-${idx}`} style={{ marginBottom: 6 }}>
                    {/* Step row */}
                    <div
                      onClick={() => handleStepClick(`${row.toolID}::${row.step}`)}
                      style={{
                        display: "grid",
                        gridTemplateColumns: "28px 90px 1fr 70px 140px 100px",
                        alignItems: "center",
                        gap: 8,
                        padding: "10px 14px",
                        background: isExpanded ? "#ebf4ff" : hasOoc ? "#fff5f5" : "#ffffff",
                        border: `1px solid ${isExpanded ? "#bee3f8" : hasOoc ? "#fed7d7" : "#e2e8f0"}`,
                        borderRadius: isExpanded ? "8px 8px 0 0" : 8,
                        cursor: "pointer",
                        fontSize: 12,
                        transition: "background 0.12s",
                      }}
                    >
                      {/* Index */}
                      <span style={{ fontSize: 11, color: "#a0aec0", fontFamily: "monospace", textAlign: "right" }}>
                        {String(idx + 1).padStart(2, "0")}
                      </span>

                      {/* Tool */}
                      <span style={{ color: "#2b6cb0", fontWeight: 500, fontFamily: "monospace" }}>
                        {row.toolID}
                      </span>

                      {/* Step */}
                      <span style={{ color: "#1a202c", fontWeight: 500 }}>
                        {row.step}
                      </span>

                      {/* SPC status badge */}
                      <span style={{
                        padding: "2px 8px",
                        borderRadius: 10,
                        fontSize: 10,
                        fontWeight: 700,
                        background: `${spcColor}20`,
                        color: spcColor,
                        textAlign: "center",
                        border: `1px solid ${spcColor}40`,
                      }}>
                        {row.spcStatus || "—"}
                      </span>

                      {/* Timestamp */}
                      <span style={{ color: "#718096", fontFamily: "monospace", fontSize: 11 }}>
                        {new Date(row.timestamp).toLocaleString("zh-TW", { hour12: false })}
                      </span>

                      {/* Actions */}
                      <span style={{ display: "flex", gap: 4, justifyContent: "flex-end" }}>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setTriggerMessage(
                              `請分析 lot ${selectedLot.lot_id} 在 ${row.toolID} 的步驟 ${row.step}，SPC狀態: ${row.spcStatus || "N/A"}。請說明此步驟的製程品質。`
                            );
                          }}
                          style={{
                            padding: "3px 8px",
                            background: "#ebf4ff",
                            border: "1px solid #bee3f8",
                            borderRadius: 4,
                            fontSize: 10,
                            color: "#2b6cb0",
                            cursor: "pointer",
                          }}
                        >
                          診斷
                        </button>
                        <span style={{ color: "#a0aec0", fontSize: 11, padding: "3px 0" }}>
                          {isExpanded ? "▲" : "▼"}
                        </span>
                      </span>
                    </div>

                    {/* Expanded: DC + SPC objects */}
                    {isExpanded && (
                      <div style={{
                        border: "1px solid #bee3f8",
                        borderTop: "none",
                        borderRadius: "0 0 8px 8px",
                        background: "#f8fbff",
                        padding: 16,
                      }}>
                        {loadingObjects ? (
                          <div style={{ textAlign: "center", color: "#a0aec0", fontSize: 12, padding: 12 }}>載入物件資料...</div>
                        ) : !stepObjects ? (
                          <div style={{ textAlign: "center", color: "#a0aec0", fontSize: 12, padding: 12 }}>無資料</div>
                        ) : (
                          <div style={{ display: "flex", gap: 16 }}>
                            {/* DC Parameters */}
                            <div style={{ flex: 1 }}>
                              <div style={{ fontSize: 11, fontWeight: 700, color: "#2b6cb0", marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.5px" }}>
                                DC 感測器數值
                              </div>
                              {!stepObjects.dc ? (
                                <div style={{ fontSize: 12, color: "#a0aec0" }}>無 DC 資料</div>
                              ) : (
                                <div style={{
                                  display: "grid",
                                  gridTemplateColumns: "repeat(3, 1fr)",
                                  gap: 4,
                                  background: "#ffffff",
                                  border: "1px solid #e2e8f0",
                                  borderRadius: 6,
                                  padding: 10,
                                  maxHeight: 220,
                                  overflowY: "auto",
                                }}>
                                  {Object.entries(stepObjects.dc.parameters ?? {}).map(([key, val]) => (
                                    <div key={key} style={{ display: "flex", justifyContent: "space-between", gap: 4, padding: "3px 0", borderBottom: "1px solid #f0f0f0", fontSize: 11 }}>
                                      <span style={{ color: "#718096", fontFamily: "monospace" }}>{key}</span>
                                      <span style={{ color: "#1a202c", fontWeight: 500, fontFamily: "monospace" }}>{typeof val === "number" ? val.toFixed(3) : String(val)}</span>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>

                            {/* SPC Charts summary */}
                            <div style={{ flex: 1 }}>
                              <div style={{ fontSize: 11, fontWeight: 700, color: "#805ad5", marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.5px" }}>
                                SPC 管制圖結果
                              </div>
                              {!stepObjects.spc ? (
                                <div style={{ fontSize: 12, color: "#a0aec0" }}>無 SPC 資料</div>
                              ) : (
                                <div style={{
                                  background: "#ffffff",
                                  border: "1px solid #e2e8f0",
                                  borderRadius: 6,
                                  overflow: "hidden",
                                }}>
                                  {/* Overall status */}
                                  <div style={{
                                    padding: "8px 12px",
                                    borderBottom: "1px solid #f0f0f0",
                                    display: "flex",
                                    alignItems: "center",
                                    gap: 8,
                                    fontSize: 12,
                                  }}>
                                    <span style={{ color: "#718096" }}>總體狀態:</span>
                                    <span style={{
                                      padding: "2px 8px",
                                      borderRadius: 8,
                                      fontSize: 11,
                                      fontWeight: 700,
                                      background: `${SPC_COLOR[stepObjects.spc.spc_status ?? ""] ?? "#a0aec0"}20`,
                                      color: SPC_COLOR[stepObjects.spc.spc_status ?? ""] ?? "#a0aec0",
                                    }}>
                                      {stepObjects.spc.spc_status ?? "—"}
                                    </span>
                                  </div>

                                  {/* Per-chart breakdown */}
                                  {Object.entries(stepObjects.spc.charts ?? {}).map(([chartName, chart]) => {
                                    const ooc = chart.value > chart.ucl || chart.value < chart.lcl;
                                    const chartStatus = ooc ? "OOC" : "PASS";
                                    const range = (chart.ucl - chart.lcl) || 1;
                                    const pct = Math.min(100, Math.max(0, ((chart.value - chart.lcl) / range) * 100));
                                    return (
                                      <div key={chartName} style={{
                                        display: "grid",
                                        gridTemplateColumns: "70px 1fr 60px",
                                        alignItems: "center",
                                        gap: 8,
                                        padding: "7px 12px",
                                        borderBottom: "1px solid #f7f8fc",
                                        fontSize: 11,
                                      }}>
                                        <span style={{ fontFamily: "monospace", fontWeight: 600, color: "#4a5568" }}>{chartName}</span>
                                        <div style={{ position: "relative", height: 6, background: "#e2e8f0", borderRadius: 3, overflow: "hidden" }}>
                                          <div style={{
                                            position: "absolute",
                                            left: `${pct}%`,
                                            top: 0,
                                            width: 4,
                                            height: "100%",
                                            background: ooc ? "#e53e3e" : "#38a169",
                                            borderRadius: 2,
                                            transform: "translateX(-50%)",
                                          }} />
                                        </div>
                                        <span style={{
                                          padding: "1px 6px",
                                          borderRadius: 6,
                                          fontSize: 10,
                                          fontWeight: 700,
                                          background: `${SPC_COLOR[chartStatus]}20`,
                                          color: SPC_COLOR[chartStatus],
                                          textAlign: "center",
                                        }}>
                                          {chartStatus}
                                        </span>
                                      </div>
                                    );
                                  })}
                                </div>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </>
          )}
        </main>

        {/* ── Right: AI Co-Pilot ── */}
        <aside style={{ width: 360, flexShrink: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <AICopilot
            triggerMessage={triggerMessage}
            onTriggerConsumed={() => setTriggerMessage(null)}
            contextEquipment={selectedLot ? selectedLot.lot_id : null}
            onContract={(c) => { setContract(c); setInvestigateMode(true); }}
          />
        </aside>
      </div>
    </div>
  );
}
