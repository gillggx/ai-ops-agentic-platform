"use client";

/**
 * Knowledge-graph view (port of reference view-graph.jsx).
 * Cards laid out in kind columns; ego-edges fade in on hover, persist on click.
 *
 * Layers (priority):
 *   - hero      = activeId ↔ neighbours (strong, kind-coloured)
 *   - secondary = neighbour ↔ neighbour (medium)
 *   - ambient   = high-co-occurrence pairs only when nothing active (very faint)
 */

import { useMemo, useState } from "react";
import {
  RunRecord, FocusRef, Kind, KIND_ORDER, KIND_COLOR, KIND_LABEL,
} from "../lib/types";
import type { ObjNode } from "../lib/types";

interface OntologyShape {
  objs:      Map<string, ObjNode>;
  neighbors: (id: string) => Set<string>;
}

interface Props {
  runs:        RunRecord[];
  ontology:    OntologyShape;
  focus:       FocusRef | null;
  onFocus:     (f: FocusRef | null) => void;
  density?:    "compact" | "comfy" | "loose";
  anomalyEmph?: "none" | "subtle" | "strong";
}

const FIELD_OF: Record<Kind, keyof RunRecord> = {
  tool:   "toolID",
  lot:    "lotID",
  recipe: "recipeID",
  apc:    "apcID",
  step:   "step",
  fdc:    "fdcID",
  spc:    "spcID",
};

interface Pos { x: number; y: number; midY: number; rightX: number; kind: Kind; }
interface Edge { a: string; b: string; count: number; alarm: boolean; }

export default function GraphView({
  runs, ontology, focus, onFocus,
  density = "comfy", anomalyEmph = "subtle",
}: Props) {
  const [hoverId, setHoverId] = useState<string | null>(null);

  // Active objects per kind in window
  const active = useMemo<Record<Kind, (ObjNode & { runs: number; alarms: number })[]>>(() => {
    const map: Record<Kind, Map<string, ObjNode & { runs: number; alarms: number }>> = {
      tool: new Map(), lot: new Map(), recipe: new Map(),
      apc: new Map(), step: new Map(), fdc: new Map(), spc: new Map(),
    };
    for (const r of runs) {
      for (const k of KIND_ORDER) {
        const id = r[FIELD_OF[k]] as string;
        if (!id) continue;
        const o = ontology.objs.get(id); if (!o) continue;
        const m = map[k];
        if (!m.has(id)) m.set(id, { ...o, runs: 0, alarms: 0 });
        const a = m.get(id)!;
        a.runs++; if (r.status === "alarm") a.alarms++;
      }
    }
    const out = {} as Record<Kind, (ObjNode & { runs: number; alarms: number })[]>;
    for (const k of KIND_ORDER) out[k] = [...map[k].values()].sort((a, b) => b.runs - a.runs);
    return out;
  }, [runs, ontology]);

  // Layout
  const COL_W  = density === "loose" ? 160 : density === "compact" ? 130 : 144;
  const ROW_H  = density === "loose" ? 34  : density === "compact" ? 28  : 30;
  const CARD_H = density === "loose" ? 28  : density === "compact" ? 24  : 26;
  const PAD_X = 32;
  const PAD_Y = 64;

  const positions = useMemo<Record<string, Pos>>(() => {
    const pos: Record<string, Pos> = {};
    KIND_ORDER.forEach((k, ci) => {
      const x = PAD_X + ci * COL_W;
      active[k].forEach((o, ri) => {
        pos[o.id] = {
          x,
          y:      PAD_Y + ri * ROW_H,
          midY:   PAD_Y + ri * ROW_H + CARD_H / 2,
          rightX: x + COL_W - 30,
          kind:   k,
        };
      });
    });
    return pos;
  }, [active, COL_W, ROW_H, CARD_H]);

  // Edges in window
  const edgeMap = useMemo<Map<string, Edge>>(() => {
    const map = new Map<string, Edge>();
    for (const r of runs) {
      const ids: string[] = [];
      for (const k of KIND_ORDER) {
        const id = r[FIELD_OF[k]] as string;
        if (id) ids.push(id);
      }
      for (let i = 0; i < ids.length; i++) {
        for (let j = i + 1; j < ids.length; j++) {
          const a = ids[i], b = ids[j];
          const key = a < b ? `${a}|${b}` : `${b}|${a}`;
          const m = map.get(key) ?? { a: a < b ? a : b, b: a < b ? b : a, count: 0, alarm: false };
          m.count++;
          if (r.status === "alarm") m.alarm = true;
          map.set(key, m);
        }
      }
    }
    return map;
  }, [runs]);

  const maxRows = Math.max(...KIND_ORDER.map((k) => active[k].length), 1);
  const W = PAD_X * 2 + KIND_ORDER.length * COL_W;
  const H = PAD_Y + maxRows * ROW_H + 30;

  const activeId = focus?.id ?? hoverId;
  const activeKindOf = activeId ? ontology.objs.get(activeId)?.kind ?? null : null;

  // Sort edges into hero / secondary / ambient
  const heroEdges:      Edge[] = [];
  const secondaryEdges: Edge[] = [];
  const ambientEdges:   Edge[] = [];

  if (activeId) {
    const neighbours = new Set<string>();
    for (const e of edgeMap.values()) {
      if (e.a === activeId || e.b === activeId) {
        if (positions[e.a] && positions[e.b]) {
          heroEdges.push(e);
          neighbours.add(e.a === activeId ? e.b : e.a);
        }
      }
    }
    for (const e of edgeMap.values()) {
      if (e.a === activeId || e.b === activeId) continue;
      if (neighbours.has(e.a) && neighbours.has(e.b) && positions[e.a] && positions[e.b]) {
        secondaryEdges.push(e);
      }
    }
  } else {
    for (const e of edgeMap.values()) {
      if (e.count >= 4 && positions[e.a] && positions[e.b]) ambientEdges.push(e);
    }
  }

  const drawPath = (e: Edge, opts: { key: string; stroke: string; sw: number; opacity: number }) => {
    const a = positions[e.a], b = positions[e.b];
    if (!a || !b) return null;
    const left  = a.x <= b.x ? a : b;
    const right = a.x <= b.x ? b : a;
    const x0 = left.rightX, y0 = left.midY;
    const x1 = right.x,     y1 = right.midY;
    const cx1 = (x0 + x1) / 2;
    const d = `M ${x0} ${y0} C ${cx1} ${y0}, ${cx1} ${y1}, ${x1} ${y1}`;
    return <path key={opts.key} d={d} stroke={opts.stroke} strokeWidth={opts.sw} fill="none" opacity={opts.opacity} />;
  };

  const isHero     = (id: string) => id === activeId;
  const isNeighbor = (id: string) => {
    if (!activeId) return false;
    return edgeMap.has(activeId < id ? `${activeId}|${id}` : `${id}|${activeId}`);
  };
  const isNeighborKind = (otherKind: Kind): boolean => {
    if (!activeId) return false;
    for (const e of edgeMap.values()) {
      if (e.a === activeId || e.b === activeId) {
        const nid = e.a === activeId ? e.b : e.a;
        if (ontology.objs.get(nid)?.kind === otherKind) return true;
      }
    }
    return false;
  };

  return (
    <div style={{ position: "relative", flex: 1, overflow: "auto", background: "#fff" }}>
      <div style={{ position: "relative", width: W, height: H, minHeight: "100%" }}>
        {/* Column headers */}
        {KIND_ORDER.map((k, ci) => (
          <div key={k} style={{
            position: "absolute", left: PAD_X + ci * COL_W, top: 26,
            width: COL_W - 16, fontSize: 10, letterSpacing: "0.14em",
            color: KIND_COLOR[k], fontWeight: 600,
            opacity: !activeKindOf || activeKindOf === k || isNeighborKind(k) ? 1 : 0.35,
            transition: "opacity .25s",
          }}>
            {KIND_LABEL[k]}
            <span style={{ color: "#cdcdcd", fontWeight: 400, marginLeft: 6 }}>{active[k].length}</span>
          </div>
        ))}

        {/* SVG edges */}
        <svg width={W} height={H} style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
          {!activeId && ambientEdges.map((e, i) =>
            drawPath(e, { key: `a${i}`, stroke: "#eaecef", sw: 0.6, opacity: 0.55 }),
          )}
          {secondaryEdges.map((e, i) =>
            drawPath(e, { key: `s${i}`, stroke: "#dfe3e8", sw: 0.7, opacity: 0.7 }),
          )}
          {heroEdges.map((e, i) => {
            const c = activeKindOf ? KIND_COLOR[activeKindOf] : "#666";
            const alarmOn = e.alarm && anomalyEmph !== "none";
            return drawPath(e, {
              key: `h${i}`,
              stroke: alarmOn ? "#e0245e" : c,
              sw: Math.min(2.2, 0.8 + Math.log2(e.count + 1) * 0.5),
              opacity: alarmOn ? 0.85 : 0.55,
            });
          })}
        </svg>

        {/* Cards */}
        {KIND_ORDER.map((k) => active[k].map((o) => {
          const p = positions[o.id]; if (!p) return null;
          const hero    = isHero(o.id);
          const neigh   = isNeighbor(o.id);
          const dimmed  = !!activeId && !hero && !neigh;
          const color   = KIND_COLOR[k];
          const hasAlarm = o.alarms > 0 && anomalyEmph !== "none";

          return (
            <div
              key={o.id}
              onClick={() => onFocus(hero ? null : { kind: k, id: o.id })}
              onMouseEnter={() => setHoverId(o.id)}
              onMouseLeave={() => setHoverId((prev) => (prev === o.id ? null : prev))}
              style={{
                position: "absolute",
                left: p.x, top: p.y,
                width: COL_W - 30, height: CARD_H,
                border: `1px solid ${hero ? color : `${color}55`}`,
                borderLeft: `3px solid ${color}`,
                background: "#fff",
                boxShadow: hero  ? `0 0 0 4px ${color}1c, 0 6px 16px ${color}28`
                         : neigh ? `0 0 0 2px ${color}14`
                         : "none",
                borderRadius: 2, cursor: "pointer",
                opacity: dimmed ? 0.18 : 1,
                transition: "opacity .22s, box-shadow .22s, border-color .22s",
                padding: "0 8px",
                display: "flex", alignItems: "center", justifyContent: "space-between",
                fontSize: 10.5, color: "#222",
                fontVariantNumeric: "tabular-nums",
                zIndex: hero ? 3 : neigh ? 2 : 1,
              }}
            >
              <span style={{ fontWeight: hero ? 600 : 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {o.name}
              </span>
              <span style={{ display: "flex", gap: 4, alignItems: "center", flexShrink: 0 }}>
                {hasAlarm && <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#e0245e" }} />}
                <span style={{ fontSize: 9.5, color: "#aaa" }}>{o.runs}</span>
              </span>
            </div>
          );
        }))}

        {!activeId && (
          <div style={{
            position: "absolute", left: PAD_X, bottom: 14,
            fontSize: 10.5, color: "#bbb", letterSpacing: "0.06em",
          }}>
            hover any object to preview · click to make it the protagonist · click again to release
          </div>
        )}
      </div>
    </div>
  );
}
