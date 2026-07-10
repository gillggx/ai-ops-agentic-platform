"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import ResultsBody from "@/components/pipeline-builder/ResultsBody";
import type { PipelineResultSummary, NodeResult } from "@/lib/pipeline-builder/types";

/**
 * /pipeline-view/[id] — read-only single-pipeline viewer.
 *
 * Loads a saved pipeline by id, shows its block chain (structure), and runs it
 * once on load to render the chart / table / verdict output. No editing — a
 * lightweight "look at this one pipeline + its result" URL (e.g. to eyeball a
 * pipeline built via the API). For editing use /admin/pipeline-builder/[id].
 */

type AnyObj = Record<string, unknown>;

function parseJson(v: unknown): AnyObj {
  if (v && typeof v === "object") return v as AnyObj;
  if (typeof v === "string") {
    try { return JSON.parse(v) as AnyObj; } catch { return {}; }
  }
  return {};
}

const NW = 184, NH = 56, GX = 244, GY = 92, PAD = 16;

// Read-only layered DAG layout (longest-path depth → left-to-right layers).
// API-built pipelines often carry no node positions, so we always lay out fresh.
function layoutDag(nodes: AnyObj[], edges: AnyObj[]) {
  const ids = nodes.map((n) => String(n.id));
  const incoming: Record<string, string[]> = {};
  ids.forEach((i) => { incoming[i] = []; });
  edges.forEach((e) => {
    const f = String((e.from as AnyObj)?.node ?? "");
    const t = String((e.to as AnyObj)?.node ?? "");
    if (incoming[t] != null && ids.includes(f)) incoming[t].push(f);
  });
  const depth: Record<string, number> = {};
  const calc = (id: string, seen: Set<string>): number => {
    if (depth[id] != null) return depth[id];
    if (seen.has(id)) return 0;
    seen.add(id);
    const ins = incoming[id] ?? [];
    const v = ins.length ? Math.max(...ins.map((p) => calc(p, seen) + 1)) : 0;
    depth[id] = v; return v;
  };
  ids.forEach((i) => calc(i, new Set()));
  const layers: Record<number, string[]> = {};
  ids.forEach((i) => { (layers[depth[i]] ??= []).push(i); });
  const pos: Record<string, { x: number; y: number }> = {};
  Object.keys(layers).map(Number).sort((a, b) => a - b).forEach((L) => {
    layers[L].forEach((id, idx) => { pos[id] = { x: PAD + L * GX, y: PAD + idx * GY }; });
  });
  const maxLayer = Math.max(0, ...Object.keys(layers).map(Number));
  const maxRows = Math.max(1, ...Object.values(layers).map((a) => a.length));
  return { pos, width: PAD * 2 + maxLayer * GX + NW, height: PAD * 2 + (maxRows - 1) * GY + NH };
}

export default function PipelineViewPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [meta, setMeta] = useState<AnyObj | null>(null);
  const [pj, setPj] = useState<AnyObj | null>(null);
  const [result, setResult] = useState<AnyObj | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function run(pipelineId: string) {
    setRunning(true); setErr(null);
    try {
      const r = await fetch(`/api/pipeline-builder/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pipeline_id: Number(pipelineId) }),
      });
      const d = await r.json();
      setResult(d?.data ?? d);
    } catch (e) {
      setErr(`執行失敗：${String(e)}`);
    } finally {
      setRunning(false);
    }
  }

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await fetch(`/api/pipeline-builder/pipelines/${id}`, { cache: "no-store" });
        const d = await r.json();
        const m = (d?.data ?? d) as AnyObj;
        if (!alive) return;
        setMeta(m);
        setPj(parseJson(m?.pipeline_json ?? m?.pipelineJson));
        setLoading(false);
        run(id);
      } catch (e) {
        if (alive) { setErr(`載入失敗：${String(e)}`); setLoading(false); }
      }
    })();
    return () => { alive = false; };
  }, [id]);

  const nodes = (pj?.nodes as AnyObj[]) ?? [];
  const edges = (pj?.edges as AnyObj[]) ?? [];
  const summary = parseJson(result?.result_summary);
  const charts = (summary?.charts as AnyObj[]) ?? [];
  const dataViews = (summary?.data_views as AnyObj[]) ?? [];
  const nodeResults = parseJson(result?.node_results);
  const status = (result?.status as string) ?? (running ? "running…" : "");

  const card: React.CSSProperties = { background: "#fff", border: "1px solid #e5e7eb", borderRadius: 12, padding: "16px 18px", marginBottom: 16 };
  const tag: React.CSSProperties = { fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 999, background: "var(--pl, #eff6ff)", color: "var(--p, #1d4ed8)", border: "1px solid var(--p, #bfdbfe)" };

  return (
    <div style={{ maxWidth: 1040, margin: "0 auto", padding: "24px 20px 80px", fontFamily: "-apple-system,Segoe UI,Roboto,sans-serif", color: "#1f2933" }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", borderBottom: "2px solid #101828", paddingBottom: 10, marginBottom: 18 }}>
        <div>
          <div style={{ fontSize: 12, color: "#6b7280", letterSpacing: ".05em", textTransform: "uppercase" }}>Pipeline #{id}</div>
          <h1 style={{ fontSize: 22, margin: "4px 0 0" }}>{(meta?.name as string) ?? (loading ? "載入中…" : "(未命名)")}</h1>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {meta?.status ? <span style={tag}>{String(meta.status)}</span> : null}
          <button onClick={() => run(id)} disabled={running} style={{ fontSize: 13, padding: "6px 14px", borderRadius: 8, border: "1px solid var(--p, #1d4ed8)", background: running ? "var(--pl, #eef2ff)" : "var(--p, #1d4ed8)", color: running ? "var(--p, #1d4ed8)" : "#fff", cursor: running ? "default" : "pointer" }}>
            {running ? "執行中…" : "重新執行"}
          </button>
          <Link href={`/admin/pipeline-builder/${id}`} style={{ fontSize: 13, color: "var(--p, #1d4ed8)", textDecoration: "none" }}>編輯 →</Link>
        </div>
      </div>

      {err ? <div style={{ ...card, background: "#fef3f2", borderColor: "#fecaca", color: "#b42318" }}>{err}</div> : null}

      <div style={card}>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10, color: "#101828" }}>結構（{nodes.length} blocks · {edges.length} edges）</div>
        {(() => {
          const { pos, width, height } = layoutDag(nodes, edges);
          return (
            <div style={{ overflowX: "auto" }}>
              <svg width={Math.max(width, 320)} height={Math.max(height, 80)} style={{ display: "block" }}>
                <defs>
                  <marker id="arr" markerWidth="9" markerHeight="9" refX="7.5" refY="4.5" orient="auto">
                    <path d="M0,0 L9,4.5 L0,9 z" fill="#94a3b8" />
                  </marker>
                </defs>
                {edges.map((e, i) => {
                  const f = pos[String((e.from as AnyObj)?.node)];
                  const t = pos[String((e.to as AnyObj)?.node)];
                  if (!f || !t) return null;
                  const x1 = f.x + NW, y1 = f.y + NH / 2, x2 = t.x - 4, y2 = t.y + NH / 2, mx = (x1 + x2) / 2;
                  return <path key={i} d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`} fill="none" stroke="#cbd5e1" strokeWidth={1.6} markerEnd="url(#arr)" />;
                })}
                {nodes.map((n) => {
                  const nid = String(n.id);
                  const p = pos[nid];
                  if (!p) return null;
                  const nr = parseJson(nodeResults[nid]);
                  const st = nr?.status as string | undefined;
                  const dot = st === "success" ? "#067647" : st === "failed" ? "#b42318" : "#9ca3af";
                  const isOut = /chart|view|alert|panel/.test(String(n.block_id));
                  return (
                    <g key={nid}>
                      <rect x={p.x} y={p.y} width={NW} height={NH} rx={10} fill={isOut ? "var(--pl, #eff6ff)" : "#fff"} stroke={isOut ? "#93c5fd" : "#e5e7eb"} strokeWidth={1.3} />
                      <circle cx={p.x + 15} cy={p.y + 19} r={4} fill={dot} />
                      <text x={p.x + 28} y={p.y + 23} fontSize={12.5} fontWeight={600} fill="#101828">{String(n.block_id).replace("block_", "")}</text>
                      <text x={p.x + 15} y={p.y + 43} fontSize={11} fill="#6b7280">{nid}{typeof nr?.rows === "number" ? ` · ${nr.rows as number} rows` : ""}</text>
                    </g>
                  );
                })}
              </svg>
            </div>
          );
        })()}
      </div>

      <div style={card}>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10, color: "#101828" }}>
          結果 {status ? <span style={{ fontWeight: 400, color: "#6b7280" }}>· {status}</span> : null}
        </div>
        {running && charts.length === 0 ? <div style={{ color: "#6b7280", fontSize: 13 }}>執行中，請稍候…</div> : null}
        {/* Unified: same ResultsBody renderer as the builder try-run / skill steps. */}
        <ResultsBody
          summary={(summary ?? {}) as unknown as PipelineResultSummary}
          nodeResults={(nodeResults ?? {}) as unknown as Record<string, NodeResult>}
          pipelineJson={pj ?? undefined}
        />
      </div>
    </div>
  );
}
