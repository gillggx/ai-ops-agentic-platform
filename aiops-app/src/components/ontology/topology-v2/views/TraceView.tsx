"use client";

/**
 * Multi-Lane Trace — primary view (port of reference view-trace.jsx).
 *
 * Insight: it's a network, not a table. Each event-star is a "run" with
 * satellites radiating around it. Overlap is solved by DEPTH not stratification:
 *   - default: all events at full opacity, hairline strokes
 *   - hover an event: its cluster pops, others dim to 22%
 *   - click an event: persistent focus + select panel on right
 *   - click a satellite, then "EXPAND AS NEW LANE": adds a child lane below
 *     showing all runs touching that object, with a same-process bracket
 *     connecting parent satellite to child centre.
 */

import { useMemo, useState, useRef, useEffect, useLayoutEffect } from "react";
import {
  RunRecord, Kind, FocusRef, KIND_LABEL,
} from "../lib/types";
import type { ObjNode } from "../lib/types";

const SATELLITES: Kind[] = ["tool", "lot", "recipe", "apc", "step", "fdc", "spc"];
const HR = 3600000;

const INK     = "#1f2328";
const INK_2   = "#5b6470";
const INK_3   = "#8a93a0";
const HAIR    = "#e6e8ec";
const PAPER   = "#fff";
const PAPER_2 = "#fafbfc";
const ACCENT  = "#c96442";

// 7 fixed angles around the centre (one per kind). Stable per-kind so adjacent
// events offset their satellites at predictable positions.
const SAT_ANGLES: Record<Kind, number> = {
  tool:   -Math.PI / 2 - 0.6,    // upper-left
  recipe: -Math.PI / 2,          // top
  apc:    -Math.PI / 2 + 0.6,    // upper-right
  step:    0,                    // right (we have 7 kinds, ref had 6)
  lot:     Math.PI / 2 - 0.6,    // lower-right
  fdc:     Math.PI / 2,          // bottom
  spc:     Math.PI / 2 + 0.6,    // lower-left
};

const FIELD_OF: Record<Kind, keyof RunRecord> = {
  tool:   "toolID",
  lot:    "lotID",
  recipe: "recipeID",
  apc:    "apcID",
  step:   "step",
  fdc:    "fdcID",
  spc:    "spcID",
};

interface Selected {
  kind:  "event" | "object";
  id:    string;
  runId: string;
  lane:  number;
}

interface HoverRun { runId: string; lane: number; }
interface LaneOrigin { fromLane: number; fromRunId: string; }

interface OntologyShape {
  objs:      Map<string, ObjNode>;
  neighbors: (id: string) => Set<string>;
}

interface Props {
  runs:        RunRecord[];           // visible runs (already windowed)
  ontology:    OntologyShape;
  windowRange: [number, number];
  focus:       FocusRef | null;
  onFocus:     (f: FocusRef | null) => void;
  linkStyle:   "underline" | "border" | "tint";
}

// ─────────────────────────────────────────────────────────────────────────
// Main view
// ─────────────────────────────────────────────────────────────────────────

export default function TraceView({
  runs, ontology, windowRange, focus, onFocus, linkStyle = "underline",
}: Props) {
  const [t0, t1] = windowRange;
  const span     = t1 - t0;

  // ── Lanes: list of object IDs currently shown as their own row ────────
  const initialLanes = useMemo<string[]>(() => {
    if (focus) return [focus.id];
    // Default: pick the lot with most events in window
    const counts = new Map<string, number>();
    for (const r of runs) counts.set(r.lotID, (counts.get(r.lotID) ?? 0) + 1);
    let best: string | null = null, bestN = 0;
    for (const [k, v] of counts) if (v > bestN) { bestN = v; best = k; }
    return best ? [best] : [];
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const [lanes,    setLanes]    = useState<string[]>(initialLanes);
  const [selected, setSelected] = useState<Selected | null>(null);
  const [hoverRun, setHoverRun] = useState<HoverRun | null>(null);
  const [origin,   setOrigin]   = useState<Record<string, LaneOrigin>>({});
  const [zoom,     setZoom]     = useState<number>(1.5);
  const [tickDensity, setTickDensity] = useState<number>(1);

  // External focus changes (e.g. from search) → ensure that id is a lane
  useEffect(() => {
    if (focus && !lanes.includes(focus.id)) {
      setLanes((ls) => [focus.id, ...ls]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus]);

  const addLane = (id: string, fromLaneIdx: number, fromRunId: string) => {
    setLanes((ls) => {
      if (ls.includes(id)) return ls;
      const next = [...ls];
      next.splice(fromLaneIdx + 1, 0, id);
      return next;
    });
    setOrigin((o) => ({ ...o, [id]: { fromLane: fromLaneIdx, fromRunId } }));
  };
  const removeLane = (id: string) => {
    setLanes((ls) => ls.filter((x) => x !== id));
    setOrigin((o) => { const n = { ...o }; delete n[id]; return n; });
    if (selected?.id === id) setSelected(null);
  };

  // Helper: events that touch a given object id (in any field)
  const laneEvents = (id: string): RunRecord[] => runs
    .filter((r) => SATELLITES.some((k) => r[FIELD_OF[k]] === id))
    .sort((a, b) => Date.parse(a.eventTime) - Date.parse(b.eventTime));

  // ── Layout constants ───────────────────────────────────────────────────
  const LABEL_W  = 170;
  const PAD_R    = 24;
  const CENTER_W = 86;
  const CENTER_H = 26;
  const SAT_W    = 64;
  const SAT_H    = 18;
  const RING_R   = 60;
  const LANE_H   = 240;

  const reset = () => {
    setLanes(initialLanes);
    setOrigin({});
    setSelected(null);
    setHoverRun(null);
    setZoom(1.5);
    setTickDensity(1);
  };

  // ── Responsive width ───────────────────────────────────────────────────
  const wrapRef = useRef<HTMLDivElement>(null);
  const [baseW, setBaseW] = useState<number>(900);
  useLayoutEffect(() => {
    const upd = () => {
      if (!wrapRef.current) return;
      setBaseW(Math.max(400, wrapRef.current.clientWidth - LABEL_W - PAD_R - (selected ? 320 : 0)));
    };
    upd();
    const ro = new ResizeObserver(upd);
    if (wrapRef.current) ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, [selected]);
  const areaW = Math.round(baseW * zoom);

  const xForT = (tIso: string | number) => {
    const t = typeof tIso === "string" ? Date.parse(tIso) : tIso;
    return ((t - t0) / span) * areaW;
  };

  // ── Active focus (selected or hovered) ─────────────────────────────────
  const activeFocus = useMemo<HoverRun | null>(() => {
    if (selected) return { runId: selected.runId, lane: selected.lane };
    if (hoverRun) return hoverRun;
    return null;
  }, [selected, hoverRun]);

  // ── Connectors + same-process brackets ─────────────────────────────────
  interface Connector { ax: number; ay: number; childTop: number; laneIdx: number; }
  const connectors: Connector[] = useMemo(() => {
    const out: Connector[] = [];
    lanes.forEach((id, idx) => {
      const o = origin[id]; if (!o) return;
      const originRun = runs.find((r) => r.id === o.fromRunId); if (!originRun) return;
      const childKind = ontology.objs.get(id)?.kind;
      if (!childKind) return;
      const angA = SAT_ANGLES[childKind] ?? Math.PI / 2;
      const ax = xForT(originRun.eventTime) + Math.cos(angA) * RING_R;
      const ay = o.fromLane * LANE_H + LANE_H / 2 + Math.sin(angA) * RING_R + SAT_H / 2;
      const childTop = idx * LANE_H;
      out.push({ ax, ay, childTop, laneIdx: idx });
    });
    return out;
  }, [lanes, origin, runs, areaW, ontology, t0, t1]);

  interface Bracket { left: number; right: number; topY: number; botY: number; }
  const sameProcRects: Bracket[] = useMemo(() => {
    const out: Bracket[] = [];
    lanes.forEach((id, idx) => {
      const o = origin[id]; if (!o) return;
      const originRun = runs.find((r) => r.id === o.fromRunId); if (!originRun) return;
      const childRun  = laneEvents(id).find((r) => r.id === o.fromRunId); if (!childRun) return;
      const childKind = ontology.objs.get(id)?.kind;
      if (!childKind) return;
      const angA = SAT_ANGLES[childKind] ?? Math.PI / 2;
      const satX    = xForT(originRun.eventTime) + Math.cos(angA) * RING_R;
      const satTopY = o.fromLane * LANE_H + LANE_H / 2 + Math.sin(angA) * RING_R - SAT_H / 2;
      const cX      = xForT(childRun.eventTime);
      const cTopY   = idx * LANE_H + LANE_H / 2 - CENTER_H / 2;
      const cBotY   = cTopY + CENTER_H;
      const left    = Math.min(satX - SAT_W / 2 - 4, cX - 28);
      const right   = Math.max(satX + SAT_W / 2 + 4, cX + 28);
      out.push({ left, right, topY: satTopY - 3, botY: cBotY + 3 });
    });
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lanes, origin, runs, areaW, ontology, t0, t1]);

  // ── Lane styling for expanded children ─────────────────────────────────
  const expandedLaneIdx = useMemo(
    () => new Set(lanes.map((id, i) => (origin[id] ? i : -1)).filter((i) => i >= 0)),
    [lanes, origin],
  );
  const isExpanded   = (idx: number) => expandedLaneIdx.has(idx);
  const laneTint     = (idx: number) => (linkStyle === "tint"   && isExpanded(idx)) ? "#f0eee9" : null;
  const laneBorderL  = (idx: number) => (linkStyle === "border" && isExpanded(idx)) ? `2px solid ${INK}` : "none";

  // ── Pointer (movable time cursor) ──────────────────────────────────────
  const [pointerT, setPointerT] = useState<number>(t0 + span / 2);
  useEffect(() => { setPointerT(t0 + span / 2); }, [t0, t1, span]);

  const scrollRef = useRef<HTMLDivElement>(null);
  const onPointerChange = (t: number) => {
    setPointerT(t);
    if (!scrollRef.current) return;
    const el = scrollRef.current;
    const pct = (t - t0) / span;
    const target = pct * areaW - el.clientWidth / 2 + LABEL_W / 2;
    el.scrollLeft = Math.max(0, Math.min(el.scrollWidth - el.clientWidth, target));
  };
  const onScroll = () => {
    if (!scrollRef.current) return;
    const el = scrollRef.current;
    const centerX = el.scrollLeft + el.clientWidth / 2 - LABEL_W / 2;
    const pct = Math.max(0, Math.min(1, centerX / areaW));
    setPointerT(t0 + pct * span);
  };

  // ── Drag-to-pan on background ──────────────────────────────────────────
  const dragRef = useRef({ active: false, startX: 0, startScroll: 0 });
  const onPanDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    dragRef.current = { active: true, startX: e.clientX, startScroll: scrollRef.current?.scrollLeft ?? 0 };
    document.body.style.cursor = "grabbing";
    const move = (ev: MouseEvent) => {
      if (!dragRef.current.active || !scrollRef.current) return;
      scrollRef.current.scrollLeft = dragRef.current.startScroll - (ev.clientX - dragRef.current.startX);
    };
    const up = () => {
      dragRef.current.active = false;
      document.body.style.cursor = "";
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };

  // ── Event-star sub-component (closes over state) ───────────────────────
  function EventStar({ run, protagonistId, laneIdx }: { run: RunRecord; protagonistId: string; laneIdx: number; }) {
    const x       = xForT(run.eventTime);
    const yC      = LANE_H / 2;
    const protKind = ontology.objs.get(protagonistId)?.kind;
    const sats    = SATELLITES.filter((k) => k !== protKind);
    const isAlarm = run.status === "alarm";
    const isSel   = selected?.kind === "event" && selected.runId === run.id && selected.lane === laneIdx;
    const focused = !!(activeFocus && activeFocus.runId === run.id && activeFocus.lane === laneIdx);
    const dimmed  = !!(activeFocus && !focused);
    const depth: "fg" | "bg" | "normal" = dimmed ? "bg" : (focused ? "fg" : "normal");

    const satPos = sats.map((k) => {
      const ang = SAT_ANGLES[k] ?? 0;
      return { k, sx: x + Math.cos(ang) * RING_R, sy: yC + Math.sin(ang) * RING_R };
    });

    return (
      <g>
        {/* spokes */}
        {satPos.map(({ k, sx, sy }) => (
          <line
            key={`sp-${k}`}
            x1={x} y1={yC} x2={sx} y2={sy}
            stroke={focused ? INK_2 : HAIR}
            strokeWidth={focused ? 1.2 : 1}
            opacity={dimmed ? 0.25 : (focused ? 1 : 0.7)}
          />
        ))}
        {/* satellites */}
        {satPos.map(({ k, sx, sy }) => {
          const sid       = (run[FIELD_OF[k]] as string) ?? "";
          if (!sid) return null;
          const sObj      = ontology.objs.get(sid);
          const sSel      = selected?.kind === "object" && selected.id === sid && selected.runId === run.id;
          const sExpanded = lanes.includes(sid);
          return (
            <Block
              key={k}
              x={sx} y={sy} w={SAT_W} h={SAT_H}
              kindLabel={KIND_LABEL[k]}
              name={sObj?.name ?? sid}
              lit={sSel}
              depth={depth}
              expanded={sExpanded}
              onClick={(e) => { e.stopPropagation(); setSelected({ kind: "object", id: sid, runId: run.id, lane: laneIdx }); }}
              onMouseEnter={() => !selected && setHoverRun({ runId: run.id, lane: laneIdx })}
              onMouseLeave={() => !selected && setHoverRun(null)}
            />
          );
        })}
        {/* centre */}
        <Block
          x={x} y={yC} w={CENTER_W} h={CENTER_H}
          kindLabel={`${protKind ? KIND_LABEL[protKind] : ""} · RUN`}
          name={run.id.slice(0, 18)}
          alarm={isAlarm}
          lit={isSel}
          accent
          depth={depth}
          onClick={(e) => { e.stopPropagation(); setSelected({ kind: "event", id: protagonistId, runId: run.id, lane: laneIdx }); }}
          onMouseEnter={() => !selected && setHoverRun({ runId: run.id, lane: laneIdx })}
          onMouseLeave={() => !selected && setHoverRun(null)}
        />
      </g>
    );
  }

  // ── Render ─────────────────────────────────────────────────────────────
  return (
    <div ref={wrapRef} style={{ flex: 1, overflow: "hidden", background: PAPER, position: "relative", display: "flex" }}>
      <div ref={scrollRef} onScroll={onScroll} style={{ flex: 1, overflow: "auto", position: "relative" }}>
        {/* Toolbar */}
        <div style={{
          position: "sticky", top: 0, zIndex: 5, background: PAPER,
          borderBottom: `1px solid ${HAIR}`,
          display: "flex", alignItems: "center", gap: 18,
          padding: "8px 18px", fontSize: 10, color: INK_3, letterSpacing: "0.08em",
        }}>
          <span style={{ fontWeight: 600, color: INK }}>TRACE</span>
          <Knob label="ZOOM"  value={zoom}        min={1}   max={4} step={0.25} onChange={setZoom}        fmt={(v) => `${v.toFixed(2)}×`} />
          <Knob label="TICKS" value={tickDensity} min={0.5} max={3} step={0.25} onChange={setTickDensity} fmt={(v) => `${v.toFixed(2)}×`} />
          <div style={{ flex: 1 }} />
          <span style={{ color: INK_3, fontSize: 9.5 }}>
            {selected ? "click background to release · " : "hover to highlight · "}
            click to select
          </span>
          <button onClick={reset} style={{
            border: `1px solid ${HAIR}`, background: PAPER, color: INK,
            fontSize: 10, letterSpacing: "0.1em", fontWeight: 600,
            padding: "5px 12px", borderRadius: 2, cursor: "pointer", fontFamily: "inherit",
          }}>↺ RESET</button>
        </div>

        {/* Lanes */}
        <div
          style={{ position: "relative", cursor: "grab" }}
          onMouseDown={onPanDown}
          onClick={() => setSelected(null)}
        >
          {lanes.map((id, idx) => {
            const obj = ontology.objs.get(id);
            if (!obj) return null;
            const events = laneEvents(id);
            return (
              <div key={id} style={{
                display: "grid", gridTemplateColumns: `${LABEL_W}px ${areaW}px ${PAD_R}px`,
                minHeight: LANE_H, borderBottom: `1px solid ${HAIR}`,
              }}>
                <div style={{
                  padding: "14px 12px 14px 18px", display: "flex", flexDirection: "column",
                  justifyContent: "center", borderRight: `1px solid ${HAIR}`,
                  borderLeft: laneBorderL(idx),
                  background: laneTint(idx) ?? (idx === 0 ? PAPER : PAPER_2),
                  position: "sticky", left: 0, zIndex: 2,
                }}>
                  <div style={{ fontSize: 9.5, letterSpacing: "0.14em", color: INK_3, fontWeight: 600, marginBottom: 3 }}>
                    {KIND_LABEL[obj.kind]} VIEW
                  </div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: INK, fontFamily: "ui-monospace, Menlo, monospace" }}>
                    {obj.name}
                  </div>
                  <div style={{ fontSize: 10, color: INK_3, marginTop: 3 }}>
                    {events.length} events · {events.filter((r) => r.status === "alarm").length} alarm
                  </div>
                  {idx > 0 && (
                    <button onClick={(e) => { e.stopPropagation(); removeLane(id); }} style={{
                      border: "none", background: "transparent", color: INK_3,
                      fontSize: 10, cursor: "pointer", padding: 0, marginTop: 8,
                      textAlign: "left", letterSpacing: "0.06em", fontFamily: "inherit",
                    }}>× CLOSE LANE</button>
                  )}
                  {idx === 0 && (
                    <button onClick={(e) => { e.stopPropagation(); onFocus({ kind: obj.kind, id: obj.id }); }} style={{
                      border: "none", background: "transparent", color: INK_3,
                      fontSize: 10, cursor: "pointer", padding: 0, marginTop: 8,
                      textAlign: "left", letterSpacing: "0.06em", fontFamily: "inherit",
                    }}>↳ SET AS FOCUS</button>
                  )}
                </div>
                <div style={{
                  position: "relative", height: LANE_H,
                  background: laneTint(idx) ?? "transparent",
                }}>
                  {linkStyle === "underline" && isExpanded(idx) && (
                    <div style={{
                      position: "absolute", left: 0, right: 0, top: 0, height: 2,
                      background: INK, opacity: 0.65, pointerEvents: "none", zIndex: 1,
                    }} />
                  )}
                  <svg width={areaW} height={LANE_H} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
                    <line x1={0} y1={LANE_H / 2} x2={areaW} y2={LANE_H / 2}
                          stroke={HAIR} strokeWidth={1} strokeDasharray="2 4" />
                    {/* z-order: dimmed first, focused last */}
                    {events
                      .filter((r) => !(activeFocus && activeFocus.runId === r.id && activeFocus.lane === idx))
                      .map((r) => <EventStar key={r.id} run={r} protagonistId={id} laneIdx={idx} />)}
                    {events
                      .filter((r) =>  (activeFocus && activeFocus.runId === r.id && activeFocus.lane === idx))
                      .map((r) => <EventStar key={r.id} run={r} protagonistId={id} laneIdx={idx} />)}
                  </svg>
                </div>
                <div />
              </div>
            );
          })}

          {/* Lane-to-lane connectors + brackets */}
          <svg style={{ position: "absolute", left: LABEL_W, top: 0, width: areaW, height: "100%", pointerEvents: "none" }}>
            <line x1={xForT(pointerT)} y1={0} x2={xForT(pointerT)} y2="100%"
                  stroke={ACCENT} strokeOpacity={0.35} strokeWidth={1} strokeDasharray="3 3" />
            {linkStyle === "tint" && connectors.map((c, i) => (
              <line key={i} x1={c.ax} y1={c.ay} x2={c.ax} y2={c.childTop}
                    stroke={INK} strokeWidth={2.2} strokeDasharray="6 4" opacity={0.55} />
            ))}
            {sameProcRects.map((r, i) => (
              <g key={`spr-${i}`} opacity={0.5}>
                <line x1={r.left}  y1={r.topY} x2={r.left}  y2={r.botY} stroke={INK} strokeWidth={1} strokeDasharray="4 3" />
                <line x1={r.right} y1={r.topY} x2={r.right} y2={r.botY} stroke={INK} strokeWidth={1} strokeDasharray="4 3" />
                <line x1={r.left}  y1={r.topY} x2={r.left + 5}  y2={r.topY} stroke={INK} strokeWidth={1} />
                <line x1={r.right} y1={r.topY} x2={r.right - 5} y2={r.topY} stroke={INK} strokeWidth={1} />
                <line x1={r.left}  y1={r.botY} x2={r.left + 5}  y2={r.botY} stroke={INK} strokeWidth={1} />
                <line x1={r.right} y1={r.botY} x2={r.right - 5} y2={r.botY} stroke={INK} strokeWidth={1} />
              </g>
            ))}
          </svg>
        </div>

        <TimePointer t0={t0} t1={t1} pointerT={pointerT} setPointerT={onPointerChange}
                     labelW={LABEL_W} padR={PAD_R} density={tickDensity} areaW={areaW} />
      </div>

      {selected && (
        <SelectedPanel
          selected={selected}
          ontology={ontology}
          runs={runs}
          lanes={lanes}
          onClose={() => setSelected(null)}
          onExpand={() => { addLane(selected.id, selected.lane, selected.runId); setSelected(null); }}
        />
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Block — the rounded-rect node (centre or satellite)
// ─────────────────────────────────────────────────────────────────────────

interface BlockProps {
  x: number; y: number; w: number; h: number;
  kindLabel?: string;
  name: string;
  alarm?: boolean;
  lit?: boolean;
  accent?: boolean;
  depth?: "fg" | "bg" | "normal";
  expanded?: boolean;
  onClick?: (e: React.MouseEvent) => void;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
}

function Block({
  x, y, w, h, kindLabel, name, alarm, lit, accent, depth = "normal", expanded,
  onClick, onMouseEnter, onMouseLeave,
}: BlockProps) {
  const px = x - w / 2, py = y - h / 2;
  const opacity = depth === "bg" ? 0.22 : 1;
  const stroke  = expanded ? INK
                : (accent ? ACCENT
                : (lit    ? INK
                : (depth === "fg" ? INK_2 : HAIR)));
  const sw     = expanded ? 1.3 : (lit ? 1.5 : (depth === "fg" ? 1.2 : 1));
  const fill   = expanded ? "#f0eee9"
               : (accent  ? "#fff7f3"
               : (lit     ? "#f4f5f7" : PAPER));
  return (
    <g style={{ cursor: "pointer", opacity, transition: "opacity .18s" }}
       onClick={onClick} onMouseEnter={onMouseEnter} onMouseLeave={onMouseLeave}>
      <rect x={px} y={py} width={w} height={h} rx={2}
            fill={fill} stroke={stroke} strokeWidth={sw}
            strokeDasharray={expanded ? "3 2" : "none"} />
      {kindLabel && (
        <text x={px + 6} y={py + 7.5} fontSize="6" fill={INK_3} fontWeight="600" letterSpacing="0.12em">
          {kindLabel}
        </text>
      )}
      <text
        x={px + 6}
        y={py + h - (kindLabel ? 5 : 5)}
        fontSize={kindLabel ? "9" : "10"}
        fontFamily="ui-monospace, Menlo, monospace"
        fill={alarm ? ACCENT : INK}
        fontWeight={lit ? 600 : ((depth === "fg" || expanded) ? 600 : 500)}
      >
        {name}
      </text>
      {alarm && <circle cx={px + w - 5} cy={py + 5} r={2.5} fill={ACCENT} />}
      {expanded && <circle cx={px + w - 5} cy={py + 5} r={2.2} fill={INK} />}
    </g>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// TimePointer — sticky bottom time ruler with movable cursor
// ─────────────────────────────────────────────────────────────────────────

interface PointerProps {
  t0: number; t1: number; pointerT: number; setPointerT: (t: number) => void;
  labelW: number; padR: number; density: number; areaW: number;
}

function TimePointer({ t0, t1, pointerT, setPointerT, labelW, padR, density, areaW }: PointerProps) {
  const span = t1 - t0;
  const ref = useRef<HTMLDivElement>(null);

  const onDown = (e: React.MouseEvent) => {
    const move = (ev: MouseEvent) => {
      if (!ref.current) return;
      const r = ref.current.getBoundingClientRect();
      const x = Math.max(0, Math.min(r.width, ev.clientX - r.left));
      setPointerT(t0 + (x / r.width) * span);
    };
    move(e.nativeEvent);
    const up = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };

  // Tick scale: scale by span, capped to keep tick count manageable
  const hours = Math.max(1, Math.round(span / HR));
  const minorEvery = Math.max(1, Math.round((hours / 48) * (2 / density)));
  const majorEvery = Math.max(minorEvery * 2, Math.round((hours / 48) * (6 / density)));
  const ticks: { t: number; major: boolean; day: boolean }[] = [];
  for (let i = 0; i <= hours; i += minorEvery) {
    const t = t0 + i * HR;
    const d = new Date(t);
    ticks.push({ t, major: i % majorEvery === 0, day: d.getHours() === 0 });
  }
  const pct = ((pointerT - t0) / span) * 100;
  const fmtPointer = (t: number) => new Date(t).toLocaleString("en-US",
    { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

  return (
    <div style={{
      position: "sticky", bottom: 0, background: PAPER, zIndex: 4,
      borderTop: `1px solid ${HAIR}`,
      display: "grid", gridTemplateColumns: `${labelW}px ${areaW}px ${padR}px`,
      padding: "10px 0",
    }}>
      <div style={{
        padding: "0 18px", fontSize: 9.5, letterSpacing: "0.12em", color: INK_3,
        position: "sticky", left: 0, background: PAPER,
      }}>
        TIME · {Math.round(span / 86400000)} D<br />
        <span style={{ color: INK, fontWeight: 500, fontFamily: "ui-monospace, Menlo, monospace", fontSize: 11, letterSpacing: 0 }}>
          {fmtPointer(pointerT)}
        </span>
      </div>
      <div ref={ref} onMouseDown={onDown} style={{
        position: "relative", height: 36, cursor: "ew-resize", userSelect: "none",
      }}>
        <div style={{ position: "absolute", left: 0, right: 0, top: 18, height: 1, background: HAIR }} />
        {ticks.map((tk, i) => {
          const x = ((tk.t - t0) / span) * 100;
          return (
            <div key={i} style={{
              position: "absolute", left: `${x}%`, top: 18,
              width: 1, height: tk.major ? 9 : 4,
              background: tk.major ? INK_2 : INK_3, opacity: tk.major ? 0.7 : 0.4,
              transform: "translateX(-0.5px)",
            }} />
          );
        })}
        {ticks.filter((tk) => tk.day || tk.t === t0).map((tk, i) => {
          const x = ((tk.t - t0) / span) * 100;
          const d = new Date(tk.t);
          return (
            <div key={`day-${i}`} style={{
              position: "absolute", left: `${x}%`, top: 0,
              fontSize: 9.5, color: INK, fontWeight: 600, letterSpacing: "0.05em",
              transform: x < 5 ? "translateX(2px)" : "translateX(-50%)",
              whiteSpace: "nowrap",
            }}>
              {d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}
            </div>
          );
        })}
        <div style={{
          position: "absolute", left: `${pct}%`, top: 0, bottom: 0,
          width: 0, transform: "translateX(-50%)",
        }}>
          <div style={{
            position: "absolute", left: "50%", top: 8, bottom: 0,
            width: 2, background: ACCENT, transform: "translateX(-50%)",
          }} />
          <svg width="14" height="14" style={{ position: "absolute", left: "50%", top: 0, transform: "translateX(-50%)" }}>
            <polygon points="7,12 0,0 14,0" fill={ACCENT} />
          </svg>
        </div>
      </div>
      <div />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// SelectedPanel — right side panel after a click
// ─────────────────────────────────────────────────────────────────────────

interface SelPanelProps {
  selected: Selected;
  ontology: OntologyShape;
  runs:     RunRecord[];
  lanes:    string[];
  onClose:  () => void;
  onExpand: () => void;
}

function SelectedPanel({ selected, ontology, runs, lanes, onClose, onExpand }: SelPanelProps) {
  const obj = ontology.objs.get(selected.id);
  if (!obj) return null;
  const run = runs.find((r) => r.id === selected.runId);
  const alreadyLane = lanes.includes(selected.id);

  return (
    <div onClick={(e) => e.stopPropagation()} style={{
      width: 320, borderLeft: `1px solid ${HAIR}`, background: PAPER,
      display: "flex", flexDirection: "column", flex: "0 0 auto",
    }}>
      <div style={{
        padding: "14px 18px", borderBottom: `1px solid ${HAIR}`,
        display: "flex", justifyContent: "space-between", alignItems: "flex-start",
      }}>
        <div>
          <div style={{ fontSize: 9.5, letterSpacing: "0.14em", color: INK_3, fontWeight: 600 }}>
            {KIND_LABEL[obj.kind]}{selected.kind === "event" ? " · EVENT" : ""}
          </div>
          <div style={{
            fontSize: 16, fontWeight: 600, color: INK, marginTop: 3,
            fontFamily: "ui-monospace, Menlo, monospace",
          }}>
            {obj.name}
          </div>
        </div>
        <button onClick={onClose} style={{
          border: "none", background: "transparent",
          color: INK_3, cursor: "pointer", fontSize: 18, padding: 0, fontFamily: "inherit",
        }}>×</button>
      </div>

      {run && (
        <div style={{ padding: "12px 18px", borderBottom: `1px solid ${HAIR}` }}>
          <div style={{ fontSize: 9, letterSpacing: "0.12em", color: INK_3, marginBottom: 6 }}>AT THIS EVENT</div>
          <div style={{ fontSize: 11, color: INK, lineHeight: 1.7 }}>
            <Row k="run"    v={run.id} />
            <Row k="time"   v={new Date(run.eventTime).toLocaleString("en-US",
              { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })} />
            <Row k="status" v={run.status} alarm={run.status === "alarm"} />
            {run.lotID    && <Row k="lot"    v={run.lotID} />}
            {run.step     && <Row k="step"   v={run.step} />}
            {run.toolID   && <Row k="tool"   v={run.toolID} />}
            {run.recipeID && <Row k="recipe" v={run.recipeID} />}
            {run.apcID    && <Row k="apc"    v={run.apcID} />}
            {run.fdcID    && <Row k="fdc"    v={run.fdcID} />}
            {run.spcID    && <Row k="spc"    v={run.spcID} />}
          </div>
        </div>
      )}

      <div style={{ padding: "12px 18px", borderBottom: `1px solid ${HAIR}` }}>
        <div style={{ fontSize: 9, letterSpacing: "0.12em", color: INK_3, marginBottom: 6 }}>OBJECT TOTALS</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
          <Stat label="RUNS"   v={obj.runs} />
          <Stat label="ALARMS" v={obj.alarms} accent={obj.alarms ? ACCENT : null} />
          <Stat label="LAST"   v={obj.lastT ? new Date(obj.lastT).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "—"} />
        </div>
      </div>

      <div style={{ padding: "14px 18px", flex: 1 }}>
        <button disabled={alreadyLane} onClick={onExpand} style={{
          width: "100%", padding: "10px 14px",
          border: `1px solid ${alreadyLane ? HAIR : INK}`,
          background: alreadyLane ? "#f8f8f8" : INK,
          color:      alreadyLane ? INK_3 : "#fff",
          fontSize: 11, letterSpacing: "0.1em", fontWeight: 600,
          borderRadius: 2, cursor: alreadyLane ? "default" : "pointer", fontFamily: "inherit",
        }}>
          {alreadyLane ? "ALREADY OPEN AS LANE" : `↓ EXPAND ${obj.name} AS NEW LANE`}
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Atoms
// ─────────────────────────────────────────────────────────────────────────

function Row({ k, v, alarm }: { k: string; v: string | number; alarm?: boolean }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "90px 1fr", gap: 8, padding: "2px 0" }}>
      <span style={{ color: INK_3, fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase" }}>{k}</span>
      <span style={{ color: alarm ? ACCENT : INK, fontFamily: "ui-monospace, Menlo, monospace", fontSize: 11 }}>{v}</span>
    </div>
  );
}

function Knob({ label, value, min, max, step, onChange, fmt }: {
  label: string; value: number; min: number; max: number; step: number;
  onChange: (v: number) => void; fmt?: (v: number) => string;
}) {
  return (
    <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span style={{ fontSize: 9, letterSpacing: "0.1em", color: INK_3 }}>{label}</span>
      <input type="range" min={min} max={max} step={step} value={value}
             onChange={(e) => onChange(parseFloat(e.target.value))}
             style={{ width: 110, accentColor: ACCENT }} />
      <span style={{
        fontSize: 10, color: INK, fontFamily: "ui-monospace, Menlo, monospace",
        fontVariantNumeric: "tabular-nums", minWidth: 42,
      }}>
        {fmt ? fmt(value) : value}
      </span>
    </label>
  );
}

function Stat({ label, v, accent }: { label: string; v: string | number; accent?: string | null }) {
  return (
    <div>
      <div style={{ fontSize: 9, letterSpacing: "0.1em", color: INK_3 }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 600, color: accent ?? INK, fontVariantNumeric: "tabular-nums", marginTop: 2 }}>
        {v}
      </div>
    </div>
  );
}
