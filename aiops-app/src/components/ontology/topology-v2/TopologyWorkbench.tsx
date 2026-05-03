"use client";

/**
 * Topology Workbench v2 — replaces TopologyCanvas (React Flow + Dagre).
 *
 * Data model: a stream of RUNS (one per completed process step) within an
 * outer time window; the user scrubs an inner sub-window (windowRange) which
 * is what TraceView actually renders. Trace is the only view (other kinds
 * removed at user request).
 *
 * Two embed modes:
 *   - "embedded"   — flexes inside parent (e.g. fleet detail tab)
 *   - "standalone" — fills its container (e.g. /topology page)
 * Both expose a Fullscreen toggle that mounts the workbench into a Portal at
 * document.body, sized 100vw / 100vh, ESC to exit.
 */

import { useState, useEffect, useMemo } from "react";
import { createPortal } from "react-dom";
import { FocusRef, TweaksState, DEFAULT_TWEAKS } from "./lib/types";
import { useTopologyRuns } from "./lib/useTopologyRuns";
import { deriveOntology, runsInWindow } from "./lib/adjacency";
import TopBar from "./TopBar";
import TraceView from "./views/TraceView";
import Timeline from "./Timeline";
import TweaksPanel from "./TweaksPanel";

interface Props {
  mode?:         "embedded" | "standalone";
  initialFocus?: FocusRef | null;
}

const HOUR_MS = 60 * 60 * 1000;
const DAY_MS  = 24 * HOUR_MS;

export default function TopologyWorkbench({
  mode = "embedded",
  initialFocus = null,
}: Props) {
  // outerWindow: data fetch range + timeline scrub scope (last 2 days).
  // windowRange: user-selected sub-window for the trace view (last 6 h default).
  const outerWindow = useMemo<[number, number]>(() => {
    const now = Date.now();
    return [now - 2 * DAY_MS, now];
  }, []);
  const [focus,       setFocus]      = useState<FocusRef | null>(initialFocus);
  const [query,       setQuery]      = useState<string>("");
  const [windowRange, setWindowRange] = useState<[number, number]>(() => {
    const now = Date.now();
    return [now - 6 * HOUR_MS, now];
  });
  const [tweaks,      setTweaks]     = useState<TweaksState>(DEFAULT_TWEAKS);
  const [showTweaks,  setShowTweaks] = useState(false);
  const [fullscreen,  setFullscreen] = useState(false);

  const fromIso = useMemo(() => new Date(outerWindow[0]).toISOString(), [outerWindow]);
  const toIso   = useMemo(() => new Date(outerWindow[1]).toISOString(), [outerWindow]);
  const { data, loading, error } = useTopologyRuns({ from: fromIso, to: toIso });

  const allRuns     = data?.runs ?? [];
  const visibleRuns = useMemo(
    () => runsInWindow(allRuns, windowRange[0], windowRange[1]),
    [allRuns, windowRange],
  );
  const ontology    = useMemo(() => deriveOntology(visibleRuns), [visibleRuns]);

  const onSearch = (q: string) => {
    setQuery(q);
    if (!q) return;
    const needle = q.toLowerCase();
    for (const obj of ontology.objs.values()) {
      if (obj.id.toLowerCase().includes(needle)) {
        setFocus({ kind: obj.kind, id: obj.id });
        return;
      }
    }
  };

  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setFullscreen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fullscreen]);

  const shell = (
    <div style={{
      display: "flex", flexDirection: "column",
      width: "100%", height: "100%",
      background: "#fff", color: "#222",
      fontFamily: '"Helvetica Neue", Helvetica, Arial, sans-serif',
      overflow: "hidden",
    }}>
      <TopBar
        focus={focus}
        onClearFocus={() => setFocus(null)}
        query={query}
        onSearch={onSearch}
        runCount={visibleRuns.length}
        truncated={data?.truncated ?? false}
        fullscreen={fullscreen}
        onToggleFullscreen={() => setFullscreen((f) => !f)}
        onToggleTweaks={() => setShowTweaks((s) => !s)}
      />

      <div style={{ flex: 1, position: "relative", display: "flex", minHeight: 0, overflow: "hidden" }}>
        <TraceView
          runs={visibleRuns}
          ontology={ontology}
          windowRange={windowRange}
          focus={focus}
          onFocus={setFocus}
          linkStyle={tweaks.linkStyle}
        />
      </div>

      {(loading || error) && (
        <div style={{
          flex: "0 0 auto", padding: "4px 14px",
          background: error ? "#fff5f5" : "#f7f8fc",
          borderTop: "1px solid #ececec",
          color: error ? "#c53030" : "#888",
          fontSize: 10.5, letterSpacing: "0.04em",
        }}>
          {error ? `Error: ${error}` : "Loading runs…"}
        </div>
      )}

      <Timeline
        outerWindow={outerWindow}
        selected={windowRange}
        onChange={setWindowRange}
        runs={allRuns}
      />

      {showTweaks && (
        <TweaksPanel state={tweaks} onChange={setTweaks} onClose={() => setShowTweaks(false)} />
      )}
    </div>
  );

  if (fullscreen) {
    if (typeof document === "undefined") return null;
    return createPortal(
      <div style={{ position: "fixed", inset: 0, zIndex: 9999, background: "#fff" }}>
        {shell}
      </div>,
      document.body,
    );
  }

  return (
    <div style={{
      position: "relative",
      width: "100%", height: "100%",
      minHeight: mode === "embedded" ? 480 : undefined,
      display: "flex", flexDirection: "column",
      border: mode === "embedded" ? "1px solid #ececec" : "none",
      borderRadius: mode === "embedded" ? 4 : 0,
      overflow: "hidden",
    }}>
      {shell}
    </div>
  );
}
