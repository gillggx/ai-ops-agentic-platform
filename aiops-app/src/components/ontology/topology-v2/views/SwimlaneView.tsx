"use client";

/**
 * Generic per-kind swimlane view (Tool / Recipe / APC / Step / FDC / SPC).
 * One row per object, time-axis lane of run dots. Click row to focus, click
 * dot to hop focus to a different kind (driven by the `dotJumpKind` prop).
 *
 * Lot has its own step-axis trail variant (LotTrailView).
 */

import { useMemo } from "react";
import {
  RunRecord, FocusRef, Kind, KIND_COLOR, KIND_LABEL,
} from "../lib/types";
import type { ObjNode } from "../lib/types";

interface OntologyShape {
  objs:      Map<string, ObjNode>;
  neighbors: (id: string) => Set<string>;
}

interface Props {
  runs:        RunRecord[];
  ontology:    OntologyShape;
  windowRange: [number, number];
  focus:       FocusRef | null;
  onFocus:     (f: FocusRef | null) => void;
  kind:        Exclude<Kind, "lot">;          // lot has its own view
  density?:    "compact" | "comfy" | "loose";
  anomalyEmph?: "none" | "subtle" | "strong";
  /** When user clicks a run dot, jump focus to this kind (e.g. tool view → lot). */
  dotJumpKind?: Kind;
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

const DAY_MS = 24 * 60 * 60 * 1000;

export default function SwimlaneView({
  runs, ontology, windowRange, focus, onFocus,
  kind, density = "comfy", anomalyEmph = "subtle",
  dotJumpKind = "lot",
}: Props) {
  const [t0, t1] = windowRange;
  const span     = t1 - t0;
  const field    = FIELD_OF[kind];
  const accent   = KIND_COLOR[kind];

  // Stats per object of this kind
  const stats = useMemo(() => {
    const m = new Map<string, ObjNode & { runList: RunRecord[]; toolSet: Set<string>; lotSet: Set<string>; recipeSet: Set<string> }>();
    for (const r of runs) {
      const id = r[field] as string;
      if (!id) continue;
      const o = ontology.objs.get(id);
      if (!o) continue;
      let s = m.get(id);
      if (!s) {
        s = { ...o, runList: [], toolSet: new Set(), lotSet: new Set(), recipeSet: new Set() };
        m.set(id, s);
      }
      s.runList.push(r);
      if (r.toolID)   s.toolSet.add(r.toolID);
      if (r.lotID)    s.lotSet.add(r.lotID);
      if (r.recipeID) s.recipeSet.add(r.recipeID);
    }
    return [...m.values()].sort((a, b) => (b.alarms - a.alarms) || (b.runs - a.runs));
  }, [runs, ontology, field]);

  const ROW_H = density === "loose" ? 50 : density === "compact" ? 36 : 44;
  const LANE_LABEL_W = 200;
  const RIGHT_META_W = 120;
  const PAD = 18;

  // Day grid
  const days = Math.max(1, Math.ceil(span / DAY_MS));
  const dayMarkers: number[] = [];
  for (let i = 0; i <= days; i++) dayMarkers.push(t0 + i * DAY_MS);
  const fmtDate = (t: number) => new Date(t).toLocaleDateString("en-US", { month: "short", day: "numeric" });

  // Ego check
  const focusObj = focus ? ontology.objs.get(focus.id) : null;
  const focusNeighbours = focus ? ontology.neighbors(focus.id) : new Set<string>();
  const isInEgo = (r: RunRecord) => {
    if (!focus) return true;
    return ([r.lotID, r.step, r.toolID, r.recipeID, r.apcID, r.fdcID, r.spcID]).includes(focus.id);
  };

  return (
    <div style={{ position: "relative", flex: 1, overflow: "auto", background: "#fff" }}>
      <div style={{ minWidth: 980, padding: "12px 0" }}>
        {/* Header */}
        <div style={{
          display: "grid",
          gridTemplateColumns: `${LANE_LABEL_W}px 1fr ${RIGHT_META_W}px`,
          padding: `0 ${PAD}px 8px ${PAD}px`,
          borderBottom: "1px solid #f0f0f0", position: "sticky", top: 0, background: "#fff", zIndex: 1,
        }}>
          <div style={{ fontSize: 10, letterSpacing: "0.14em", color: "#999" }}>
            {KIND_LABEL[kind]} · {stats.length}
          </div>
          <div style={{ position: "relative", height: 18 }}>
            {dayMarkers.map((t, i) => (
              <div key={i} style={{
                position: "absolute",
                left: `${((t - t0) / span) * 100}%`,
                fontSize: 9, color: "#bbb", transform: "translateX(-50%)",
                whiteSpace: "nowrap",
              }}>
                {i % Math.max(1, Math.floor(days / 7)) === 0 ? fmtDate(t) : ""}
              </div>
            ))}
          </div>
          <div style={{ fontSize: 10, letterSpacing: "0.14em", color: "#999", textAlign: "right" }}>
            RUNS · ALM
          </div>
        </div>

        {/* Lanes */}
        {stats.map((s) => {
          const isFocus = focus?.id === s.id;
          const dim     = focusObj && focusObj.kind !== kind && !focusNeighbours.has(s.id);
          return (
            <div
              key={s.id}
              onClick={() => onFocus(isFocus ? null : { kind, id: s.id })}
              style={{
                display: "grid",
                gridTemplateColumns: `${LANE_LABEL_W}px 1fr ${RIGHT_META_W}px`,
                padding: `0 ${PAD}px`,
                minHeight: ROW_H, alignItems: "center",
                borderBottom: "1px dashed #f3f3f3",
                opacity: dim ? 0.3 : 1, cursor: "pointer",
                background: isFocus ? `${accent}10` : "transparent",
                transition: "opacity .15s, background .15s",
              }}
            >
              {/* Label */}
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div style={{
                  width: 3, height: ROW_H - 16,
                  background: accent, opacity: isFocus ? 1 : 0.55,
                }} />
                <div>
                  <div style={{
                    fontSize: 12, fontWeight: 500, color: "#111",
                    fontFamily: "ui-monospace, Menlo, monospace",
                  }}>{s.name}</div>
                  <div style={{ fontSize: 9.5, color: "#999", letterSpacing: "0.06em", marginTop: 1 }}>
                    {s.lotSet.size} LOTS · {s.toolSet.size} TOOLS{kind !== "recipe" ? ` · ${s.recipeSet.size} RCP` : ""}
                  </div>
                </div>
              </div>

              {/* Lane */}
              <div style={{ position: "relative", height: ROW_H - 8 }}>
                {dayMarkers.slice(0, -1).map((d, i) => (
                  <div key={i} style={{
                    position: "absolute", top: 0, bottom: 0,
                    left: `${((d - t0) / span) * 100}%`,
                    width: `${(DAY_MS / span) * 100}%`,
                    background: i % 2 ? "transparent" : "#fafafa",
                  }} />
                ))}
                <div style={{ position: "absolute", top: "50%", left: 0, right: 0, height: 1, background: "#eee" }} />
                {s.runList.map((r) => {
                  const x   = ((Date.parse(r.eventTime) - t0) / span) * 100;
                  const ego = isInEgo(r);
                  const c   = r.status === "alarm" ? "#e0245e"
                            : r.status === "warn"  ? "#f59e0b" : accent;
                  const sz  = r.status === "alarm" ? 8 : 6;
                  return (
                    <div
                      key={r.id}
                      title={`${r.id} · ${r.lotID} · ${r.recipeID} · ${new Date(r.eventTime).toLocaleString()}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        const jumpField = FIELD_OF[dotJumpKind];
                        const jumpId = r[jumpField] as string;
                        if (jumpId) onFocus({ kind: dotJumpKind, id: jumpId });
                      }}
                      style={{
                        position: "absolute",
                        left: `calc(${x}% - ${sz / 2}px)`,
                        top:  `calc(50% - ${sz / 2}px)`,
                        width: sz, height: sz,
                        borderRadius: "50%",
                        background: ego ? c : "#fff",
                        border: `1.5px solid ${c}`,
                        opacity: ego ? 1 : 0.18,
                        cursor: "pointer",
                        boxShadow: r.status === "alarm" && anomalyEmph !== "none" && ego ? `0 0 0 3px ${c}25` : "none",
                      }}
                    />
                  );
                })}
              </div>

              {/* Right meta */}
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, alignItems: "center" }}>
                <span style={{ fontSize: 11, color: "#444", fontVariantNumeric: "tabular-nums" }}>{s.runs}</span>
                <span style={{
                  fontSize: 11, color: s.alarms ? "#e0245e" : "#bbb",
                  fontVariantNumeric: "tabular-nums", minWidth: 18, textAlign: "right",
                }}>{s.alarms || "·"}</span>
                <div style={{
                  width: 36, height: 4, background: "#f3f3f3", borderRadius: 2, overflow: "hidden",
                }}>
                  <div style={{
                    height: "100%",
                    width: `${(s.alarms / Math.max(s.runs, 1)) * 100}%`,
                    background: "#e0245e",
                  }} />
                </div>
              </div>
            </div>
          );
        })}

        {stats.length === 0 && (
          <div style={{ padding: "40px 20px", textAlign: "center", color: "#bbb", fontSize: 12 }}>
            No {KIND_LABEL[kind]} activity in current window.
          </div>
        )}
      </div>
    </div>
  );
}
