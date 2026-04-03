"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { TopologyCanvas, type TopologySnapshot, type CenterType } from "@/components/ontology/TopologyCanvas";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RawEvent {
  eventTime:  string;
  lotID:      string;
  toolID:     string;
  step:       string;
  spc_status: string;
  recipeID?:  string;
  apcID?:     string;
}

interface LotItem     { lot_id: string; status: string; current_step?: number; }
interface EquipItem   { equipment_id: string; name: string; status: string; }
interface ObjectItem  { id: string; }
interface OcapItem    { id: string; lotID: string; step: string; eventTime: string; }

type ObjectType = "LOT" | "TOOL" | "RECIPE" | "APC" | "DC" | "SPC" | "EC" | "FDC" | "OCAP";

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

const LOT_STATUS_COLOR: Record<string, string> = {
  Processing: "#38a169",
  Waiting:    "#d69e2e",
  Finished:   "#a0aec0",
};
const TOOL_STATUS_COLOR: Record<string, string> = {
  running:     "#38a169",
  idle:        "#a0aec0",
  alarm:       "#e53e3e",
  maintenance: "#d69e2e",
  down:        "#c53030",
};
const TYPE_ACCENT: Record<ObjectType, string> = {
  LOT:    "#2b6cb0",
  TOOL:   "#e53e3e",
  RECIPE: "#2c7a7b",
  APC:    "#b83280",
  DC:     "#276749",
  SPC:    "#c53030",
  EC:     "#744210",
  FDC:    "#d69e2e",
  OCAP:   "#c53030",
};

// Map ObjectType → CenterType for the canvas
function toCenterType(t: ObjectType): CenterType {
  if (t === "LOT" || t === "TOOL" || t === "RECIPE" || t === "APC") return t;
  if (t === "DC" || t === "SPC" || t === "OCAP") return "LOT";
  return "TOOL"; // EC, FDC
}

// Sidebar type layout: 3 columns × 3 rows
const TYPE_GROUPS: ObjectType[][] = [
  ["LOT",  "TOOL",   "RECIPE"],
  ["APC",  "DC",     "SPC"  ],
  ["EC",   "FDC",    "OCAP" ],
];

// ---------------------------------------------------------------------------
// Inner page
// ---------------------------------------------------------------------------

function TopologyPageInner() {
  const searchParams = useSearchParams();
  const router       = useRouter();

  const initType = (searchParams.get("type") ?? "LOT").toUpperCase() as ObjectType;
  const initId   = searchParams.get("id") ?? "";

  const [objectType, setObjectType]       = useState<ObjectType>(initType);
  const [selectedId, setSelectedId]       = useState<string>(initId);
  const [lots, setLots]                   = useState<LotItem[]>([]);
  const [tools, setTools]                 = useState<EquipItem[]>([]);
  const [recipes, setRecipes]             = useState<ObjectItem[]>([]);
  const [apcs, setApcs]                   = useState<ObjectItem[]>([]);
  const [ocapEvents, setOcapEvents]       = useState<OcapItem[]>([]);
  const [events, setEvents]               = useState<RawEvent[]>([]);
  const [selectedEvent, setSelectedEvent] = useState<RawEvent | null>(null);
  const [snapshot, setSnapshot]           = useState<TopologySnapshot | null>(null);
  const [loadingSnap, setLoadingSnap]     = useState(false);

  // ── Fetch object lists on mount ─────────────────────────────────────────

  useEffect(() => {
    const order: Record<string, number> = { Processing: 0, Waiting: 1, Finished: 2 };

    fetch("/api/ontology/lots")
      .then((r) => r.json())
      .then((data: LotItem[]) => {
        data.sort((a, b) => (order[a.status] ?? 3) - (order[b.status] ?? 3));
        setLots(data);
      })
      .catch(() => {});

    fetch("/api/ontology/equipment")
      .then((r) => r.json())
      .then((data: { items: EquipItem[] }) => setTools(data.items ?? []))
      .catch(() => {});

    fetch("/api/ontology/objects?type=RECIPE")
      .then((r) => r.json())
      .then((data: { items: ObjectItem[] }) => setRecipes(data.items ?? []))
      .catch(() => {});

    fetch("/api/ontology/objects?type=APC")
      .then((r) => r.json())
      .then((data: { items: ObjectItem[] }) => setApcs(data.items ?? []))
      .catch(() => {});

    fetch("/api/ontology/objects?type=OCAP")
      .then((r) => r.json())
      .then((data: { items: OcapItem[] }) => setOcapEvents(data.items ?? []))
      .catch(() => {});
  }, []);

  // ── Fetch events for selected object ────────────────────────────────────

  const fetchEvents = useCallback(async (type: ObjectType, id: string) => {
    if (!id) return;

    // OCAP: id = "LOT-xxx|STEP_yyy" — set event directly, no timeline needed
    if (type === "OCAP") {
      const item = ocapEvents.find((e) => e.id === id);
      if (item) {
        const synthetic: RawEvent = {
          eventTime: item.eventTime,
          lotID:     item.lotID,
          toolID:    "",
          step:      item.step,
          spc_status: "",
        };
        setEvents([synthetic]);
        setSelectedEvent(synthetic);
      }
      return;
    }

    let qs: string;
    switch (type) {
      case "LOT":
      case "DC":
      case "SPC":
        qs = `lot_id=${encodeURIComponent(id)}`;       break;
      case "TOOL":
      case "EC":
      case "FDC":
        qs = `equipment_id=${encodeURIComponent(id)}`; break;
      case "RECIPE":
        qs = `recipe_id=${encodeURIComponent(id)}`;    break;
      case "APC":
        qs = `apc_id=${encodeURIComponent(id)}`;       break;
    }
    try {
      const res = await fetch(`/api/ontology/events?${qs}&limit=200`);
      if (!res.ok) return;
      const data = await res.json();
      const raw: RawEvent[] = (data.items ?? []).map((e: Record<string, unknown>) => {
        const meta = e.metadata as Record<string, unknown> | undefined;
        return {
          eventTime:  e.timestamp    as string ?? "",
          lotID:      meta?.lotID    as string ?? "",
          toolID:     e.equipment_id as string ?? "",
          step:       meta?.step     as string ?? "",
          spc_status: meta?.spc_status as string ?? "",
          recipeID:   meta?.recipeID   as string ?? "",
          apcID:      meta?.apcID      as string ?? "",
        };
      });
      raw.sort((a, b) => new Date(a.eventTime).getTime() - new Date(b.eventTime).getTime());
      setEvents(raw);
      if (raw.length > 0) setSelectedEvent(raw[raw.length - 1]);
    } catch { /* ignore */ }
  }, [ocapEvents]);

  useEffect(() => {
    setEvents([]);
    setSelectedEvent(null);
    setSnapshot(null);
    if (selectedId) fetchEvents(objectType, selectedId);
  }, [objectType, selectedId, fetchEvents]);

  // ── Fetch topology snapshot when event changes ───────────────────────────

  useEffect(() => {
    if (!selectedEvent?.step) return;

    const lotId = objectType === "LOT" ? selectedId : selectedEvent.lotID;
    if (!lotId) return;

    setLoadingSnap(true);
    setSnapshot(null);

    const url = `/api/ontology/topology?lot=${encodeURIComponent(lotId)}`
      + `&step=${encodeURIComponent(selectedEvent.step)}`
      + `&eventTime=${encodeURIComponent(selectedEvent.eventTime)}`;

    fetch(url)
      .then((r) => r.json())
      .then((data) => setSnapshot(data as TopologySnapshot))
      .catch(() => setSnapshot(null))
      .finally(() => setLoadingSnap(false));
  }, [selectedEvent, selectedId, objectType]);

  // ── Select object ─────────────────────────────────────────────────────────

  const handleSelect = (id: string) => {
    setSelectedId(id);
    router.replace(`/topology?type=${objectType.toLowerCase()}&id=${encodeURIComponent(id)}`);
  };

  const handleTypeChange = (t: ObjectType) => {
    setObjectType(t);
    setSelectedId("");
    setEvents([]);
    setSelectedEvent(null);
    setSnapshot(null);
    router.replace(`/topology?type=${t.toLowerCase()}`);
  };

  // ── Timeline ──────────────────────────────────────────────────────────────

  const tEvents   = events.filter((e) => e.step);
  const timeMin   = tEvents.length > 0 ? new Date(tEvents[0].eventTime).getTime() : 0;
  const timeMax   = tEvents.length > 0 ? new Date(tEvents[tEvents.length - 1].eventTime).getTime() : 1;
  const timeRange = timeMax - timeMin || 1;
  const xPct      = (ev: RawEvent) => ((new Date(ev.eventTime).getTime() - timeMin) / timeRange) * 92 + 4;

  const oocCount  = tEvents.filter((e) => e.spc_status === "OOC").length;
  const passCount = tEvents.filter((e) => e.spc_status === "PASS").length;

  // ── Object list for current type ──────────────────────────────────────────

  type ListItem = { id: string; label: string; sub: string; statusColor: string };

  const currentList: ListItem[] = (() => {
    switch (objectType) {
      case "LOT":
        return lots.map((l) => ({
          id:          l.lot_id,
          label:       l.lot_id,
          sub:         l.status + (l.current_step != null ? ` · Step ${l.current_step}` : ""),
          statusColor: LOT_STATUS_COLOR[l.status] ?? "#a0aec0",
        }));
      case "TOOL":
        return tools.map((t) => ({
          id:          t.equipment_id,
          label:       t.equipment_id,
          sub:         t.name,
          statusColor: TOOL_STATUS_COLOR[t.status] ?? "#a0aec0",
        }));
      case "RECIPE":
        return recipes.map((r) => ({
          id: r.id, label: r.id, sub: "", statusColor: TYPE_ACCENT.RECIPE,
        }));
      case "APC":
        return apcs.map((a) => ({
          id: a.id, label: a.id, sub: "", statusColor: TYPE_ACCENT.APC,
        }));
      case "DC":
        return lots.map((l) => ({
          id:          l.lot_id,
          label:       l.lot_id,
          sub:         `DC · ${l.status}`,
          statusColor: LOT_STATUS_COLOR[l.status] ?? "#a0aec0",
        }));
      case "SPC":
        return lots.map((l) => ({
          id:          l.lot_id,
          label:       l.lot_id,
          sub:         `SPC · ${l.status}`,
          statusColor: LOT_STATUS_COLOR[l.status] ?? "#a0aec0",
        }));
      case "EC":
        return tools.map((t) => ({
          id:          t.equipment_id,
          label:       t.equipment_id,
          sub:         `EC · ${t.name}`,
          statusColor: TOOL_STATUS_COLOR[t.status] ?? "#a0aec0",
        }));
      case "FDC":
        return tools.map((t) => ({
          id:          t.equipment_id,
          label:       t.equipment_id,
          sub:         `FDC · ${t.name}`,
          statusColor: TOOL_STATUS_COLOR[t.status] ?? "#a0aec0",
        }));
      case "OCAP":
        return ocapEvents.map((o) => ({
          id:          o.id,
          label:       o.lotID,
          sub:         o.step,
          statusColor: "#c53030",
        }));
    }
  })();

  const listCountLabel: Record<ObjectType, string> = {
    LOT:    `Lots (${lots.length})`,
    TOOL:   `Tools (${tools.length})`,
    RECIPE: `Recipes (${recipes.length})`,
    APC:    `APCs (${apcs.length})`,
    DC:     `DC Lots (${lots.length})`,
    SPC:    `SPC Lots (${lots.length})`,
    EC:     `EC Tools (${tools.length})`,
    FDC:    `FDC Tools (${tools.length})`,
    OCAP:   `OCAP Events (${ocapEvents.length})`,
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "#f7f8fc", overflow: "hidden" }}>
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>

        {/* ── Left sidebar ── */}
        <aside style={{
          width: 220,
          flexShrink: 0,
          background: "#ffffff",
          borderRight: "1px solid #e2e8f0",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}>
          {/* Object type selector — 3-col grid */}
          <div style={{ padding: "12px 10px 8px", borderBottom: "1px solid #e2e8f0" }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: "#a0aec0", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 8 }}>
              Object Type
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              {TYPE_GROUPS.map((row, ri) => (
                <div key={ri} style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 3 }}>
                  {row.map((t) => {
                    const active = objectType === t;
                    const accent = TYPE_ACCENT[t];
                    return (
                      <button
                        key={t}
                        onClick={() => handleTypeChange(t)}
                        title={t}
                        style={{
                          padding: "5px 4px",
                          borderRadius: 5,
                          cursor: "pointer",
                          background: active ? `${accent}18` : "transparent",
                          border: active ? `1px solid ${accent}50` : "1px solid #e2e8f0",
                          color: active ? accent : "#718096",
                          fontSize: 11,
                          fontWeight: active ? 700 : 400,
                          textAlign: "center",
                          lineHeight: 1,
                        }}
                      >
                        {t}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          </div>

          {/* Object list */}
          <div style={{ flex: 1, overflowY: "auto", padding: "8px 8px" }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: "#a0aec0", textTransform: "uppercase", letterSpacing: "0.5px", padding: "4px 4px 6px" }}>
              {listCountLabel[objectType]}
            </div>
            {currentList.length === 0 && (
              <div style={{ fontSize: 11, color: "#cbd5e0", padding: "8px 4px" }}>載入中...</div>
            )}
            {currentList.map((item) => {
              const active = selectedId === item.id;
              const accent = TYPE_ACCENT[objectType];
              return (
                <button
                  key={item.id}
                  onClick={() => handleSelect(item.id)}
                  style={{
                    display: "block", width: "100%", textAlign: "left",
                    padding: "8px 10px", borderRadius: 6, marginBottom: 2, cursor: "pointer",
                    background: active ? `${accent}14` : "transparent",
                    border: active ? `1px solid ${accent}40` : "1px solid transparent",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ width: 7, height: 7, borderRadius: "50%", background: item.statusColor, flexShrink: 0, display: "inline-block" }} />
                    <span style={{ fontFamily: "monospace", fontSize: 12, fontWeight: 600, color: active ? accent : "#1a202c" }}>
                      {item.label}
                    </span>
                  </div>
                  {item.sub && (
                    <div style={{ fontSize: 10, color: "#a0aec0", paddingLeft: 13, marginTop: 1 }}>{item.sub}</div>
                  )}
                </button>
              );
            })}
          </div>
        </aside>

        {/* ── Center: canvas + timeline ── */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, overflow: "hidden" }}>

          {/* Context bar */}
          {selectedId && (
            <div style={{
              height: 40, flexShrink: 0,
              background: "#ffffff", borderBottom: "1px solid #e2e8f0",
              display: "flex", alignItems: "center", padding: "0 20px", gap: 14,
              fontSize: 12,
            }}>
              <span style={{
                fontSize: 10, fontWeight: 600, letterSpacing: 1, padding: "2px 7px", borderRadius: 4,
                background: `${TYPE_ACCENT[objectType]}14`, color: TYPE_ACCENT[objectType],
                border: `1px solid ${TYPE_ACCENT[objectType]}40`,
              }}>
                {objectType}
              </span>
              <span style={{ fontFamily: "monospace", fontWeight: 600, color: "#1a202c" }}>
                {objectType === "OCAP" ? selectedId.split("|")[0] : selectedId}
              </span>
              {tEvents.length > 0 && <span style={{ color: "#a0aec0" }}>· {tEvents.length} events</span>}
              {oocCount > 0 && (
                <span style={{ fontWeight: 700, color: "#c53030", background: "#fff5f5", border: "1px solid #fed7d7", padding: "1px 8px", borderRadius: 8 }}>
                  {oocCount} OOC
                </span>
              )}
              {selectedEvent && (
                <>
                  <span style={{ color: "#e2e8f0" }}>|</span>
                  <span style={{ color: "#a0aec0" }}>STEP</span>
                  <span style={{ fontFamily: "monospace", color: "#1a202c" }}>{selectedEvent.step}</span>
                  <span style={{ color: "#a0aec0" }}>{selectedEvent.toolID}</span>
                  {snapshot?.spc?.spc_status && (
                    <span style={{
                      fontWeight: 700, fontSize: 11, padding: "1px 8px", borderRadius: 8,
                      background: snapshot.spc.spc_status === "OOC" ? "#fff5f5" : "#f0fff4",
                      color:      snapshot.spc.spc_status === "OOC" ? "#c53030"  : "#276749",
                      border:     `1px solid ${snapshot.spc.spc_status === "OOC" ? "#fed7d7" : "#c6f6d5"}`,
                    }}>
                      {snapshot.spc.spc_status}
                    </span>
                  )}
                </>
              )}
            </div>
          )}

          {/* Topology canvas */}
          <TopologyCanvas
            snapshot={snapshot}
            centerType={toCenterType(objectType)}
            centerId={selectedId || undefined}
            loading={loadingSnap}
          />

          {/* Timeline — hidden for OCAP (event is pre-selected) */}
          {objectType !== "OCAP" && (
            <div style={{
              height: 96, flexShrink: 0,
              background: "#ffffff", borderTop: "1px solid #e2e8f0",
              padding: "8px 20px 6px",
            }}>
              <div style={{ display: "flex", gap: 14, alignItems: "center", marginBottom: 6, fontSize: 11 }}>
                {[["#4299e1","Start"],["#c53030","OOC End"],["#38a169","Pass End"]].map(([c, l]) => (
                  <div key={l} style={{ display: "flex", gap: 5, alignItems: "center" }}>
                    <span style={{ width: 7, height: 7, borderRadius: "50%", background: c, display: "inline-block" }} />
                    <span style={{ color: "#a0aec0" }}>{l}</span>
                  </div>
                ))}
                <div style={{ marginLeft: "auto", color: "#a0aec0", fontSize: 11 }}>
                  {tEvents.length} events · {oocCount} OOC · {passCount} PASS
                </div>
              </div>

              <div style={{ position: "relative", height: 40, userSelect: "none" }}>
                <div style={{ position: "absolute", left: "4%", right: "4%", top: 10, height: 1, background: "#e2e8f0" }} />

                {tEvents.map((ev, i) => {
                  const pct        = xPct(ev);
                  const isSelected = ev === selectedEvent;
                  const color      = ev.spc_status === "OOC" ? "#c53030" : ev.spc_status === "PASS" ? "#38a169" : "#cbd5e0";
                  return (
                    <div key={i}
                      onClick={() => setSelectedEvent(ev)}
                      title={`${ev.step} @ ${new Date(ev.eventTime).toLocaleString("zh-TW", { hour12: false })}`}
                      style={{
                        position: "absolute", left: `${pct}%`, top: isSelected ? 2 : 4,
                        width: isSelected ? 3 : 2, height: isSelected ? 22 : 16,
                        background: isSelected ? "#2b6cb0" : color,
                        borderRadius: 1, cursor: "pointer", transform: "translateX(-50%)", zIndex: isSelected ? 2 : 1,
                      }}
                    />
                  );
                })}

                {selectedEvent && (
                  <div style={{
                    position: "absolute", left: `${xPct(selectedEvent)}%`, top: 28,
                    transform: "translateX(-50%)",
                    background: "#ebf4ff", border: "1px solid #bee3f8",
                    borderRadius: 4, padding: "1px 6px",
                    fontSize: 10, color: "#2b6cb0", whiteSpace: "nowrap", pointerEvents: "none",
                  }}>
                    {selectedEvent.step}
                  </div>
                )}
              </div>

              {tEvents.length > 1 && (
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "#cbd5e0", marginTop: 2 }}>
                  <span>{new Date(timeMin).toLocaleString("zh-TW", { hour12: false, month: "numeric", day: "numeric", hour: "numeric", minute: "numeric" })}</span>
                  <span>{new Date(timeMax).toLocaleString("zh-TW", { hour12: false, month: "numeric", day: "numeric", hour: "numeric", minute: "numeric" })}</span>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Suspense boundary
// ---------------------------------------------------------------------------

export default function TopologyPage() {
  return (
    <Suspense fallback={
      <div style={{ height: "100vh", background: "#f7f8fc", display: "flex", alignItems: "center", justifyContent: "center", color: "#a0aec0" }}>
        載入...
      </div>
    }>
      <TopologyPageInner />
    </Suspense>
  );
}
