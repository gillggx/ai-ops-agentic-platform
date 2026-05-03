"use client";

/**
 * Right-side ego-neighbor panel. Port of reference app-chrome.jsx FocusPanel.
 * Visible whenever focus is set AND tweaks.showFocusPanel is true.
 *
 * Note: TraceView has its own SelectedPanel (richer per-event detail). This
 * FocusPanel is for non-trace views (Graph, swimlane variants) where there's
 * no per-event panel, but you still want to see "what is connected to this".
 */

import { useMemo } from "react";
import {
  RunRecord, FocusRef, Kind, KIND_ORDER, KIND_COLOR, KIND_LABEL,
} from "./lib/types";
import type { ObjNode } from "./lib/types";

interface OntologyShape {
  objs:      Map<string, ObjNode>;
  neighbors: (id: string) => Set<string>;
}

interface Props {
  focus:    FocusRef;
  ontology: OntologyShape;
  runs:     RunRecord[];
  onClose:  () => void;
  onPickRelated: (f: FocusRef) => void;
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

const fmtDate = (t: number) => new Date(t).toLocaleDateString("zh-TW", { month: "numeric", day: "numeric" });

export default function FocusPanel({ focus, ontology, runs, onClose, onPickRelated }: Props) {
  const obj = ontology.objs.get(focus.id);
  const color = KIND_COLOR[focus.kind];

  const ownRuns = useMemo(
    () => runs.filter((r) => KIND_ORDER.some((k) => r[FIELD_OF[k]] === focus.id)),
    [runs, focus.id],
  );

  const byKind = useMemo(() => {
    const out: Record<Kind, ObjNode[]> = {
      tool: [], lot: [], recipe: [], apc: [], step: [], fdc: [], spc: [],
    };
    for (const nid of ontology.neighbors(focus.id)) {
      const o = ontology.objs.get(nid);
      if (!o) continue;
      out[o.kind].push(o);
    }
    for (const k of KIND_ORDER) out[k].sort((a, b) => b.runs - a.runs);
    return out;
  }, [ontology, focus.id]);

  if (!obj) return null;

  return (
    <div style={{
      position: "absolute", top: 0, right: 0, bottom: 0, width: 320,
      background: "#fff", borderLeft: `2px solid ${color}`,
      display: "flex", flexDirection: "column",
      fontSize: 11.5, color: "#222",
      boxShadow: "-8px 0 24px rgba(0,0,0,0.04)",
      zIndex: 5,
    }}>
      <div style={{
        padding: "14px 18px", borderBottom: "1px solid #f0f0f0",
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <div>
          <div style={{ fontSize: 10, letterSpacing: "0.12em", color, fontWeight: 600 }}>
            {KIND_LABEL[focus.kind]}
          </div>
          <div style={{
            fontSize: 16, fontWeight: 500, marginTop: 2, color: "#111",
            fontFamily: "ui-monospace, Menlo, monospace",
          }}>
            {obj.name}
          </div>
        </div>
        <button onClick={onClose} style={{
          border: "none", background: "transparent", color: "#999",
          cursor: "pointer", fontSize: 18, fontFamily: "inherit",
        }}>×</button>
      </div>

      <div style={{
        padding: "12px 18px", borderBottom: "1px solid #f5f5f5",
        display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10,
      }}>
        <Stat label="RUNS · WIN" value={ownRuns.length} />
        <Stat label="ALARMS"     value={ownRuns.filter((r) => r.status === "alarm").length}
              accent={ownRuns.some((r) => r.status === "alarm") ? "#e0245e" : null} />
        <Stat label="LAST"       value={ownRuns.length ? fmtDate(Date.parse(ownRuns[ownRuns.length - 1].eventTime)) : "—"} />
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "6px 0" }}>
        <Section title="CONNECTED OBJECTS">
          {KIND_ORDER.filter((k) => byKind[k].length).map((k) => (
            <div key={k} style={{ padding: "6px 18px" }}>
              <div style={{
                fontSize: 9.5, letterSpacing: "0.1em", color: KIND_COLOR[k], marginBottom: 4,
              }}>
                {KIND_LABEL[k]} · {byKind[k].length}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {byKind[k].slice(0, 12).map((o) => (
                  <button
                    key={o.id}
                    onClick={() => onPickRelated({ kind: k, id: o.id })}
                    style={{
                      border: `1px solid ${KIND_COLOR[k]}40`,
                      background: "#fff", color: "#222",
                      padding: "2px 7px", borderRadius: 2, fontSize: 10.5,
                      fontFamily: "inherit", cursor: "pointer", letterSpacing: "0.02em",
                    }}
                  >
                    {o.name}{o.alarms ? <span style={{ color: "#e0245e", marginLeft: 4 }}>●</span> : null}
                  </button>
                ))}
                {byKind[k].length > 12 && (
                  <span style={{ fontSize: 10, color: "#aaa", alignSelf: "center" }}>+{byKind[k].length - 12}</span>
                )}
              </div>
            </div>
          ))}
        </Section>

        <Section title={`RECENT RUNS · ${ownRuns.length}`}>
          <div style={{ padding: "0 18px" }}>
            {ownRuns.slice(-12).reverse().map((r) => (
              <div key={r.id} style={{
                display: "grid", gridTemplateColumns: "55px 1fr auto",
                fontSize: 10.5, padding: "4px 0", borderBottom: "1px dashed #f0f0f0",
                color: "#444", alignItems: "center", gap: 8,
              }}>
                <span style={{ color: "#999", fontVariantNumeric: "tabular-nums" }}>
                  {fmtDate(Date.parse(r.eventTime))}
                </span>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {r.lotID} · {r.step} · {r.toolID}
                </span>
                <span style={{
                  width: 6, height: 6, borderRadius: "50%",
                  background: r.status === "alarm" ? "#e0245e"
                            : r.status === "warn"  ? "#f59e0b" : "#cbd5d8",
                }} />
              </div>
            ))}
            {ownRuns.length === 0 && (
              <div style={{ fontSize: 10.5, color: "#bbb", padding: "10px 0" }}>
                No runs in current window.
              </div>
            )}
          </div>
        </Section>
      </div>
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string | number; accent?: string | null }) {
  return (
    <div>
      <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "#999" }}>{label}</div>
      <div style={{
        fontSize: 18, fontWeight: 500, color: accent ?? "#111",
        fontVariantNumeric: "tabular-nums", marginTop: 2,
      }}>{value}</div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ padding: "8px 0" }}>
      <div style={{ fontSize: 9, letterSpacing: "0.12em", color: "#999", padding: "4px 18px 6px" }}>{title}</div>
      {children}
    </div>
  );
}
