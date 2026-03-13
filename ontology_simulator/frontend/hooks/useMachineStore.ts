"use client";
import { useEffect, useRef, useState, useCallback } from "react";
import { MachineState, Stage, WsEvent } from "@/lib/types";
import { LogType } from "@/hooks/useConsole";

// Use dynamic hostname so the app works regardless of where it's served from.
// The OntologySimulator backend always runs on port 8001.
// Evaluated lazily at call-time to avoid SSG/hydration mismatch.
function getUrls() {
  const host = typeof window !== "undefined" ? window.location.hostname : "localhost";
  return {
    ws:  `ws://${host}:8001/ws`,
    api: `http://${host}:8001/api/v1`,
  };
}
const MACHINE_IDS = Array.from({ length: 10 }, (_, i) => `EQP-${String(i + 1).padStart(2, "0")}`);

const initialMachine = (id: string): MachineState => ({
  id,
  stage: "STAGE_IDLE",
  lotId: null, recipe: null,
  apc: { active: false, mode: "" },
  dc:  { active: false, collectionPlan: "" },
  spc: { active: false },
  step: null, apcId: null,
  bias: null, biasTrend: null, biasAlert: false,
  reflection: null, lastEvent: null,
  processStartTime: null, holdType: null,
});

type AddLogFn = (type: LogType, text: string) => void;

export function useMachineStore(addLog?: AddLogFn) {
  const [machines, setMachines] = useState<Record<string, MachineState>>(
    () => Object.fromEntries(MACHINE_IDS.map(id => [id, initialMachine(id)]))
  );
  const [connected, setConnected] = useState(false);
  const wsRef      = useRef<WebSocket | null>(null);
  const idleTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const update = useCallback((id: string, patch: Partial<MachineState>) => {
    setMachines(prev => ({ ...prev, [id]: { ...prev[id], ...patch } }));
  }, []);

  // Called when user clicks ACKNOWLEDGE on a HOLD card
  const acknowledge = useCallback((id: string) => {
    setMachines(prev => {
      const m = prev[id];
      if (!m) return prev;

      if (m.holdType === "EQUIPMENT") {
        const url = `${getUrls().api}/tools/${id}/acknowledge`;
        addLog?.("API_REQ", `POST ${url}`);
        fetch(url, { method: "POST" })
          .then(r => r.json())
          .then(j => addLog?.("API_RES", `ACK ${id} → released=${j.released}`))
          .catch(err => addLog?.("ERROR", `ACK ${id} failed: ${err}`));
        return { ...prev, [id]: { ...m, stage: "STAGE_PROCESS", holdType: null } };
      } else {
        clearTimeout(idleTimers.current[id]);
        return {
          ...prev,
          [id]: {
            ...m,
            stage: "STAGE_IDLE",
            lotId: null, recipe: null,
            apc: { active: false, mode: "" },
            dc:  { active: false, collectionPlan: "" },
            spc: { active: false },
            bias: null, biasTrend: null, biasAlert: false,
            reflection: null, processStartTime: null, holdType: null,
          },
        };
      }
    });
  }, [addLog]);

  const handleEvent = useCallback((evt: WsEvent) => {
    const id = evt.machine_id;
    if (!MACHINE_IDS.includes(id)) return;

    // Log all WS events to console  (spec: "[EVENT] Received X for Y")
    const summary = evt.type === "METRIC_UPDATE"
      ? `Received METRIC_UPDATE for ${id} — bias=${evt.data.bias?.toFixed(4)} spc=${evt.data.spc_status}`
      : evt.type === "MACHINE_HOLD"
        ? `Received MACHINE_HOLD for ${id} — ${evt.data.reason}`
        : evt.type === "ENTITY_LINK"
          ? `Received ENTITY_LINK for ${id} — lot=${evt.data.lot_id} recipe=${evt.data.recipe}`
          : evt.type === "TOOL_LINK"
            ? `Received TOOL_LINK for ${id} — apc=${evt.data.apc.mode} dc=${evt.data.dc.collection_plan}`
            : `Received ${(evt as unknown as { type: string }).type} for ${id}`;
    addLog?.("WS", summary);

    if (evt.type === "ENTITY_LINK") {
      clearTimeout(idleTimers.current[id]);
      update(id, {
        stage: "STAGE_LOAD",
        lotId: evt.data.lot_id, recipe: evt.data.recipe,
        lastEvent: evt.data.timestamp,
        apc: { active: false, mode: "" },
        dc:  { active: false, collectionPlan: "" },
        spc: { active: false },
        bias: null, biasTrend: null, biasAlert: false,
        reflection: null, processStartTime: null, holdType: null,
      });

    } else if (evt.type === "TOOL_LINK") {
      update(id, {
        stage: "STAGE_PROCESS",
        apc: { active: evt.data.apc.active, mode: evt.data.apc.mode },
        dc:  { active: evt.data.dc.active,  collectionPlan: evt.data.dc.collection_plan },
        spc: { active: evt.data.spc.active },
        processStartTime: Date.now(),
        holdType: null,
      });

    } else if (evt.type === "MACHINE_HOLD") {
      update(id, {
        stage: "STAGE_DONE_OOC",
        holdType: "EQUIPMENT",
        lastEvent: evt.data.timestamp,
      });

    } else if (evt.type === "METRIC_UPDATE") {
      const d = evt.data;
      const isOOC  = d.spc_status === "OOC";
      const stage: Stage = isOOC ? "STAGE_DONE_OOC" : "STAGE_DONE_PASS";
      const stepNum = parseInt(d.step.split("_")[1]);
      const apcId   = `APC-${String(stepNum).padStart(3, "0")}`;

      update(id, {
        stage: "STAGE_ANALYSIS",
        step: d.step, apcId,
        bias: d.bias, biasTrend: d.trend, biasAlert: d.bias_alert,
        reflection: d.reflection, lastEvent: d.timestamp,
        holdType: isOOC ? "SPC" : null,
      });
      setTimeout(() => update(id, { stage }), 600);

      if (!isOOC) {
        idleTimers.current[id] = setTimeout(() => {
          update(id, {
            stage: "STAGE_IDLE", lotId: null, recipe: null,
            apc: { active: false, mode: "" }, dc: { active: false, collectionPlan: "" },
            spc: { active: false }, bias: null, biasTrend: null,
            biasAlert: false, reflection: null, processStartTime: null, holdType: null,
          });
        }, 5000);
      }
    }
  }, [update, addLog]);

  // ── Hydration: restore in-flight machine states on mount ────
  const hydrate = useCallback(async () => {
    addLog?.("SYSTEM", "Hydrating machine states from REST…");
    try {
      const [toolDocs, eventDocs] = await Promise.all([
        fetch(`${getUrls().api}/tools`).then(r => r.json()) as Promise<{ tool_id: string; status: string }[]>,
        // Fetch last event per tool for all busy machines in one shot
        fetch(`${getUrls().api}/events?limit=200`).then(r => r.json()) as Promise<{
          toolID: string; lotID: string; step: string; recipeID?: string;
          apcID?: string; eventTime: string; spc_status?: string;
        }[]>,
      ]);

      // Build a map of toolID → most recent event (events already sorted newest-first)
      const latestByTool: Record<string, typeof eventDocs[number]> = {};
      for (const e of eventDocs) {
        if (!latestByTool[e.toolID]) latestByTool[e.toolID] = e;
      }

      setMachines(prev => {
        const next = { ...prev };
        for (const tool of toolDocs) {
          const id = tool.tool_id;
          if (!MACHINE_IDS.includes(id)) continue;
          if (tool.status !== "Busy") continue;

          const ev = latestByTool[id];
          if (!ev) continue;

          const stepNum = parseInt(ev.step.split("_")[1]);
          const apcId   = `APC-${String(stepNum).padStart(3, "0")}`;
          next[id] = {
            ...prev[id],
            stage: "STAGE_PROCESS",
            lotId: ev.lotID,
            recipe: ev.recipeID ?? null,
            step:   ev.step,
            apcId,
            apc: { active: true, mode: "Run-to-Run" },
            dc:  { active: true, collectionPlan: "HIGH_FREQ" },
            spc: { active: true },
            lastEvent: ev.eventTime,
            processStartTime: Date.now(),
            holdType: null,
          };
        }
        return next;
      });
      addLog?.("SYSTEM", `Hydration complete — ${toolDocs.filter(t => t.status === "Busy").length} machines restored`);
    } catch (e) {
      addLog?.("ERROR", `Hydration failed: ${e}`);
    }
  }, [addLog]);

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  useEffect(() => {
    function connect() {
      const wsUrl = getUrls().ws;
      addLog?.("SYSTEM", `Connecting to ${wsUrl}…`);
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      ws.onopen    = () => { setConnected(true);  addLog?.("SYSTEM", "WebSocket connected"); };
      ws.onclose   = () => { setConnected(false); addLog?.("SYSTEM", "WebSocket closed — reconnecting in 3s"); setTimeout(connect, 3000); };
      ws.onerror   = () => ws.close();
      ws.onmessage = (e) => {
        try { handleEvent(JSON.parse(e.data) as WsEvent); } catch { /* ignore */ }
      };
    }
    connect();
    return () => { wsRef.current?.close(); };
  }, [handleEvent, addLog]);

  return { machines: Object.values(machines), connected, acknowledge };
}
