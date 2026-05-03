"use client";

/**
 * Topology Workbench v2 — replaces TopologyCanvas (React Flow + Dagre).
 *
 * Data model: a stream of RUNS (one per completed process step), fetched once
 * for the current 28-day window and kept in memory. All views derive from this:
 * per-kind objects, co-occurrence links, timeline density, ego subgraphs.
 *
 * Two embed modes:
 *   - "embedded"   — flexes inside parent (e.g. fleet detail tab)
 *   - "standalone" — fills its container (e.g. /topology page)
 * Both expose a Fullscreen toggle that mounts the workbench into a portal at
 * document.body, sized 100vw / 100vh, ESC to exit.
 */

import { useState, useEffect, useMemo, useRef } from "react";
import { createPortal } from "react-dom";
import {
  FocusRef, ViewKind, Kind, KIND_ORDER,
  TweaksState, DEFAULT_TWEAKS,
} from "./lib/types";
import { useTopologyRuns } from "./lib/useTopologyRuns";
import { deriveOntology, runsInWindow } from "./lib/adjacency";
import TopBar from "./TopBar";
import ViewPlaceholder from "./views/_placeholder";
import TraceView from "./views/TraceView";
import GraphView from "./views/GraphView";
import SwimlaneView from "./views/SwimlaneView";
import LotTrailView from "./views/LotTrailView";
import Timeline from "./Timeline";
import FocusPanel from "./FocusPanel";
import TweaksPanel from "./TweaksPanel";

interface Props {
  mode?:         "embedded" | "standalone";
  initialFocus?: FocusRef | null;
  initialView?:  ViewKind;
}

const DAY_MS = 24 * 60 * 60 * 1000;

export default function TopologyWorkbench({
  mode = "embedded",
  initialFocus = null,
  initialView  = "trace",
}: Props) {
  // ── State ───────────────────────────────────────────────────────────────
  // outerWindow = always 28 days (data fetch range, timeline histogram scope)
  // windowRange = user-selected sub-window (what views actually render)
  const outerWindow = useMemo<[number, number]>(() => {
    const now = Date.now();
    return [now - 28 * DAY_MS, now];
  }, []);
  const [focus,       setFocus]      = useState<FocusRef | null>(initialFocus);
  const [activeView,  setActiveView] = useState<ViewKind>(initialView);
  const [query,       setQuery]      = useState<string>("");
  const [windowRange, setWindowRange] = useState<[number, number]>(() => {
    const now = Date.now();
    return [now - 2 * DAY_MS, now];   // default: last 2 days inside the 28-d outer
  });
  const [tweaks,      setTweaks]     = useState<TweaksState>(DEFAULT_TWEAKS);
  const [showTweaks,  setShowTweaks] = useState(false);    // hidden by default per Spec
  const [fullscreen,  setFullscreen] = useState(false);

  // Fetch all runs in the OUTER 28-day window once; views + timeline filter client-side
  const fromIso = useMemo(() => new Date(outerWindow[0]).toISOString(), [outerWindow]);
  const toIso   = useMemo(() => new Date(outerWindow[1]).toISOString(), [outerWindow]);
  const { data, loading, error } = useTopologyRuns({ from: fromIso, to: toIso });

  const allRuns      = data?.runs ?? [];
  const visibleRuns  = useMemo(
    () => runsInWindow(allRuns, windowRange[0], windowRange[1]),
    [allRuns, windowRange],
  );
  const ontology     = useMemo(() => deriveOntology(visibleRuns), [visibleRuns]);

  // ── Auto-jump view when focus kind diverges from active view ────────────
  useEffect(() => {
    if (!focus) return;
    if (activeView === "graph" || activeView === "trace") return;
    if (focus.kind !== activeView) setActiveView(focus.kind);
  }, [focus, activeView]);

  // ── Search: jump focus to first matching object ─────────────────────────
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

  // ── Fullscreen: ESC handler ─────────────────────────────────────────────
  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFullscreen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fullscreen]);

  // ── Render the active view ──────────────────────────────────────────────
  const showFocusPanel = tweaks.showFocusPanel && focus && activeView !== "trace";
  // (TraceView has its own SelectedPanel, so we suppress the global FocusPanel there.)

  const ViewBody = (
    <div style={{ flex: 1, position: "relative", display: "flex", minHeight: 0, overflow: "hidden" }}>
      {activeView === "trace" ? (
        <TraceView
          runs={visibleRuns}
          ontology={ontology}
          windowRange={windowRange}
          focus={focus}
          onFocus={setFocus}
          linkStyle={tweaks.linkStyle}
        />
      ) : activeView === "graph" ? (
        <GraphView
          runs={visibleRuns}
          ontology={ontology}
          focus={focus}
          onFocus={setFocus}
          density={tweaks.density}
          anomalyEmph={tweaks.anomalyEmph}
        />
      ) : activeView === "lot" ? (
        <LotTrailView
          runs={visibleRuns}
          ontology={ontology}
          focus={focus}
          onFocus={setFocus}
          density={tweaks.density}
          anomalyEmph={tweaks.anomalyEmph}
        />
      ) : (activeView === "tool" || activeView === "recipe" || activeView === "apc"
          || activeView === "step" || activeView === "fdc" || activeView === "spc") ? (
        <SwimlaneView
          runs={visibleRuns}
          ontology={ontology}
          windowRange={windowRange}
          focus={focus}
          onFocus={setFocus}
          kind={activeView}
          density={tweaks.density}
          anomalyEmph={tweaks.anomalyEmph}
          dotJumpKind={activeView === "tool" ? "lot" : "tool"}
        />
      ) : (
        <ViewPlaceholder view={activeView} />
      )}

      {showFocusPanel && focus && (
        <FocusPanel
          focus={focus}
          ontology={ontology}
          runs={visibleRuns}
          onClose={() => setFocus(null)}
          onPickRelated={setFocus}
        />
      )}
    </div>
  );

  // ── Workbench shell (used both in-place and inside fullscreen portal) ────
  const shell = (
    <div style={{
      display: "flex", flexDirection: "column",
      width: "100%", height: "100%",
      background: "#fff", color: "#222",
      fontFamily: '"Helvetica Neue", Helvetica, Arial, sans-serif',
      overflow: "hidden",
    }}>
      <TopBar
        activeView={activeView}
        onPickView={setActiveView}
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

      {ViewBody}

      {/* Loading / error banner (subtle, above timeline) */}
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

  // ── Container styling per mode + fullscreen portal ──────────────────────
  if (fullscreen) {
    if (typeof document === "undefined") return null;
    return createPortal(
      <div style={{
        position: "fixed", inset: 0, zIndex: 9999,
        background: "#fff",
      }}>
        {shell}
      </div>,
      document.body,
    );
  }

  return (
    <div style={{
      position: "relative",
      width: "100%",
      height: mode === "standalone" ? "100%" : "100%",
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

// Suppress unused-import warning (KIND_ORDER will be consumed by views in P4-P6)
void KIND_ORDER;
