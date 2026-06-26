"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import ChartRenderer from "@/components/pipeline-builder/ChartRenderer";

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
  const tag: React.CSSProperties = { fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 999, background: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe" };

  return (
    <div style={{ maxWidth: 1040, margin: "0 auto", padding: "24px 20px 80px", fontFamily: "-apple-system,Segoe UI,Roboto,sans-serif", color: "#1f2933" }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", borderBottom: "2px solid #101828", paddingBottom: 10, marginBottom: 18 }}>
        <div>
          <div style={{ fontSize: 12, color: "#6b7280", letterSpacing: ".05em", textTransform: "uppercase" }}>Pipeline #{id}</div>
          <h1 style={{ fontSize: 22, margin: "4px 0 0" }}>{(meta?.name as string) ?? (loading ? "載入中…" : "(未命名)")}</h1>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {meta?.status ? <span style={tag}>{String(meta.status)}</span> : null}
          <button onClick={() => run(id)} disabled={running} style={{ fontSize: 13, padding: "6px 14px", borderRadius: 8, border: "1px solid #1d4ed8", background: running ? "#eef2ff" : "#1d4ed8", color: running ? "#1d4ed8" : "#fff", cursor: running ? "default" : "pointer" }}>
            {running ? "執行中…" : "重新執行"}
          </button>
          <Link href={`/admin/pipeline-builder/${id}`} style={{ fontSize: 13, color: "#1d4ed8", textDecoration: "none" }}>編輯 →</Link>
        </div>
      </div>

      {err ? <div style={{ ...card, background: "#fef3f2", borderColor: "#fecaca", color: "#b42318" }}>{err}</div> : null}

      <div style={card}>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10, color: "#101828" }}>結構（{nodes.length} blocks · {edges.length} edges）</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          {nodes.map((n, i) => {
            const nid = String(n.id);
            const nr = parseJson(nodeResults[nid]);
            const st = nr?.status as string | undefined;
            const dot = st === "success" ? "#067647" : st === "failed" ? "#b42318" : "#9ca3af";
            return (
              <span key={nid} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <span style={{ border: "1px solid #e5e7eb", borderRadius: 8, padding: "6px 10px", fontSize: 12.5, background: "#fcfcfd" }}>
                  <span style={{ display: "inline-block", width: 7, height: 7, borderRadius: 99, background: dot, marginRight: 6 }} />
                  <b>{String(n.block_id).replace("block_", "")}</b>
                  {typeof nr?.rows === "number" ? <span style={{ color: "#6b7280" }}> · {nr.rows as number} rows</span> : null}
                </span>
                {i < nodes.length - 1 ? <span style={{ color: "#9ca3af" }}>→</span> : null}
              </span>
            );
          })}
        </div>
      </div>

      <div style={card}>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10, color: "#101828" }}>
          結果 {status ? <span style={{ fontWeight: 400, color: "#6b7280" }}>· {status}</span> : null}
        </div>
        {running && charts.length === 0 ? <div style={{ color: "#6b7280", fontSize: 13 }}>執行中，請稍候…</div> : null}
        {!running && charts.length === 0 && dataViews.length === 0 ? <div style={{ color: "#6b7280", fontSize: 13 }}>（無圖表 / 表格輸出）</div> : null}
        {charts.map((c, i) => (
          <div key={i} style={{ marginBottom: 18 }}>
            <ChartRenderer spec={(c.chart_spec ?? c) as never} height={360} />
          </div>
        ))}
        {dataViews.map((dv, i) => {
          const rows = (dv.rows as AnyObj[]) ?? [];
          const cols = rows[0] ? Object.keys(rows[0]).slice(0, 8) : [];
          return (
            <div key={`dv${i}`} style={{ marginTop: 12 }}>
              <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 6 }}>{String(dv.title ?? "Table")}</div>
              <div style={{ overflowX: "auto" }}>
                <table style={{ borderCollapse: "collapse", fontSize: 12 }}>
                  <thead><tr>{cols.map((k) => <th key={k} style={{ border: "1px solid #e5e7eb", padding: "5px 8px", background: "#f8fafc", textAlign: "left" }}>{k}</th>)}</tr></thead>
                  <tbody>{rows.slice(0, 20).map((row, ri) => <tr key={ri}>{cols.map((k) => <td key={k} style={{ border: "1px solid #e5e7eb", padding: "5px 8px" }}>{String(row[k])}</td>)}</tr>)}</tbody>
                </table>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
