"use client";

/**
 * Lot view (port of reference view-lot.jsx).
 * Each lot is a row; runs sorted by step sequence (left=early, right=late) so
 * each lot's path traces as a sankey-style trail across steps.
 */

import { useMemo } from "react";
import {
  RunRecord, FocusRef, KIND_COLOR,
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

export default function LotTrailView({
  runs, ontology, focus, onFocus,
  density = "comfy", anomalyEmph = "subtle",
}: Props) {
  // Group runs by lot, sort by time
  const lotTrails = useMemo(() => {
    const m = new Map<string, RunRecord[]>();
    for (const r of runs) {
      if (!r.lotID) continue;
      const arr = m.get(r.lotID) ?? [];
      arr.push(r);
      m.set(r.lotID, arr);
    }
    const out: { lot: ObjNode; runs: RunRecord[]; alarms: number }[] = [];
    for (const [lotId, list] of m) {
      list.sort((a, b) => Date.parse(a.eventTime) - Date.parse(b.eventTime));
      const alarms = list.filter((r) => r.status === "alarm").length;
      const lot = ontology.objs.get(lotId);
      if (!lot) continue;
      out.push({ lot, runs: list, alarms });
    }
    out.sort((a, b) => (b.alarms - a.alarms) || (b.runs.length - a.runs.length));
    return out;
  }, [runs, ontology]);

  // Step axis: union of all steps observed, sorted alphanumerically
  const STEPS = useMemo(() => {
    const s = new Set<string>();
    for (const r of runs) if (r.step) s.add(r.step);
    return [...s].sort();
  }, [runs]);

  const ROW_H   = density === "loose" ? 50 : density === "compact" ? 36 : 42;
  const LABEL_W = 200;
  const META_W  = 100;

  const stepX = (sid: string): number => {
    const i = STEPS.indexOf(sid);
    return i < 0 ? 0 : (i + 0.5) / Math.max(1, STEPS.length);
  };

  const focusObj = focus ? ontology.objs.get(focus.id) : null;
  const focusNeighbours = focus ? ontology.neighbors(focus.id) : new Set<string>();
  const isInEgo = (r: RunRecord) => {
    if (!focus) return true;
    return ([r.lotID, r.step, r.toolID, r.recipeID, r.apcID, r.fdcID, r.spcID]).includes(focus.id);
  };

  return (
    <div style={{ position: "relative", flex: 1, overflow: "auto", background: "#fff" }}>
      <div style={{ minWidth: 1000, padding: "12px 0" }}>
        {/* Header: step axis */}
        <div style={{
          display: "grid",
          gridTemplateColumns: `${LABEL_W}px 1fr ${META_W}px`,
          padding: "0 18px 8px", position: "sticky", top: 0, background: "#fff", zIndex: 1,
          borderBottom: "1px solid #f0f0f0",
        }}>
          <div style={{ fontSize: 10, letterSpacing: "0.14em", color: "#999" }}>LOT · {lotTrails.length}</div>
          <div style={{ position: "relative", height: 18 }}>
            {STEPS.map((s, i) => (
              <div key={s} style={{
                position: "absolute",
                left: `${((i + 0.5) / Math.max(1, STEPS.length)) * 100}%`,
                transform: "translateX(-50%)",
                fontSize: 10, color: KIND_COLOR.step, fontWeight: 600, letterSpacing: "0.08em",
              }}>{s}</div>
            ))}
          </div>
          <div style={{ fontSize: 10, letterSpacing: "0.14em", color: "#999", textAlign: "right" }}>RUNS · ALM</div>
        </div>

        {lotTrails.map(({ lot, runs: rs, alarms }) => {
          const isFocus = focus?.id === lot.id;
          const dim     = focusObj && focusObj.kind !== "lot" && !focusNeighbours.has(lot.id);
          return (
            <div
              key={lot.id}
              onClick={() => onFocus(isFocus ? null : { kind: "lot", id: lot.id })}
              style={{
                display: "grid",
                gridTemplateColumns: `${LABEL_W}px 1fr ${META_W}px`,
                padding: "0 18px", minHeight: ROW_H,
                borderBottom: "1px dashed #f3f3f3",
                opacity: dim ? 0.25 : 1, cursor: "pointer",
                background: isFocus ? "#f5f8ff" : "transparent", alignItems: "center",
                transition: "opacity .15s, background .15s",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div style={{
                  width: 3, height: ROW_H - 16,
                  background: KIND_COLOR.lot, opacity: isFocus ? 1 : 0.55,
                }} />
                <div>
                  <div style={{
                    fontSize: 12, fontWeight: 500, color: "#111",
                    fontFamily: "ui-monospace, Menlo, monospace",
                  }}>{lot.name}</div>
                  <div style={{ fontSize: 9.5, color: "#999", letterSpacing: "0.06em", marginTop: 1 }}>
                    {rs.length} STOPS · {new Set(rs.map((r) => r.toolID)).size} TOOLS
                  </div>
                </div>
              </div>

              <div style={{ position: "relative", height: ROW_H - 12 }}>
                {STEPS.map((s, i) => (
                  <div key={s} style={{
                    position: "absolute", top: 0, bottom: 0,
                    left: `${((i + 0.5) / Math.max(1, STEPS.length)) * 100}%`,
                    width: 1, background: "#f4f4f4",
                  }} />
                ))}
                <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}
                     preserveAspectRatio="none">
                  {rs.length > 1 && (() => {
                    const pts = rs.map((r) => ({ x: stepX(r.step) * 100, y: 50 }));
                    const d = pts.map((p, i) => `${i ? "L" : "M"} ${p.x}% ${p.y}%`).join(" ");
                    return <path d={d} stroke={KIND_COLOR.lot} strokeOpacity={0.4} strokeWidth={1.5} fill="none" />;
                  })()}
                </svg>
                {rs.map((r) => {
                  const x   = stepX(r.step) * 100;
                  const ego = isInEgo(r);
                  const c   = r.status === "alarm" ? "#e0245e"
                            : r.status === "warn"  ? "#f59e0b" : KIND_COLOR.lot;
                  const sz  = r.status === "alarm" ? 9 : 7;
                  return (
                    <div
                      key={r.id}
                      title={`${r.id} · ${r.toolID} · ${r.recipeID} · ${new Date(r.eventTime).toLocaleString()}`}
                      onClick={(e) => { e.stopPropagation(); if (r.toolID) onFocus({ kind: "tool", id: r.toolID }); }}
                      style={{
                        position: "absolute",
                        left: `calc(${x}% - ${sz / 2}px)`,
                        top:  `calc(50% - ${sz / 2}px)`,
                        width: sz, height: sz, borderRadius: 2,
                        background: ego ? c : "#fff",
                        border: `1.5px solid ${c}`,
                        opacity: ego ? 1 : 0.18,
                        cursor: "pointer",
                        boxShadow: r.status === "alarm" && anomalyEmph !== "none" && ego ? `0 0 0 3px ${c}25` : "none",
                      }}
                    />
                  );
                })}
                {isFocus && rs.map((r) => {
                  const x = stepX(r.step) * 100;
                  return (
                    <div key={`${r.id}_lbl`} style={{
                      position: "absolute", left: `${x}%`,
                      transform: "translateX(-50%)",
                      bottom: -2, fontSize: 9, color: "#666", whiteSpace: "nowrap",
                      fontFamily: "ui-monospace, Menlo, monospace",
                    }}>{r.toolID}</div>
                  );
                })}
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, alignItems: "center" }}>
                <span style={{ fontSize: 11, color: "#444", fontVariantNumeric: "tabular-nums" }}>{rs.length}</span>
                <span style={{
                  fontSize: 11, color: alarms ? "#e0245e" : "#bbb",
                  minWidth: 16, textAlign: "right", fontVariantNumeric: "tabular-nums",
                }}>{alarms || "·"}</span>
              </div>
            </div>
          );
        })}

        {lotTrails.length === 0 && (
          <div style={{ padding: "40px 20px", textAlign: "center", color: "#bbb", fontSize: 12 }}>
            No lot activity in current window.
          </div>
        )}
      </div>
    </div>
  );
}
