"use client";

/**
 * Skills v2 Editor — SVG mini-canvas of the bound pipeline.
 *
 * Fetches pipeline_json by id and renders an LR DAG diagram in SVG: rounded
 * node boxes + cubic-bezier edges + verdict highlight. Lightweight (no React
 * Flow dep). Read-only; click-through is handled by the Editor's
 * "用 Pipeline Builder 編譯 →" button, not by this thumb.
 *
 * Layout: uses node.position from pipeline_json directly so it mirrors what
 * the user sees in Pipeline Builder. Falls back to a simple LR auto-layout
 * if all positions are (0,0).
 */

import { useEffect, useMemo, useState } from "react";

interface ThumbNode {
  id: string;
  block_id: string;
  display_label?: string;
  position: { x: number; y: number };
  isVerdict: boolean;
}
interface ThumbEdge { from: string; to: string }

interface Props {
  pipelineId: number | null;
  height?: number;
}

const NW = 170;
const NH = 52;
const PAD = 30;

export default function PipelineSvgThumb({ pipelineId, height = 380 }: Props) {
  const [nodes, setNodes] = useState<ThumbNode[]>([]);
  const [edges, setEdges] = useState<ThumbEdge[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!pipelineId) { setNodes([]); setEdges([]); setError(null); return; }
    setLoading(true); setError(null);
    fetch(`/api/pipeline-builder/pipelines/${pipelineId}`)
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then((env) => {
        const record = env?.data ?? env;
        // Java PipelineEntity stores pipeline_json as a TEXT column → on the
        // wire it arrives as a JSON-encoded STRING, not a nested object.
        // Parse defensively (some surfaces already deserialize it).
        const rawPj = record?.pipeline_json ?? record;
        let pj: Record<string, unknown> = {};
        if (typeof rawPj === "string") {
          try { pj = JSON.parse(rawPj); } catch { pj = {}; }
        } else if (rawPj && typeof rawPj === "object") {
          pj = rawPj as Record<string, unknown>;
        }
        const rawNodes = (pj.nodes ?? []) as Array<Record<string, unknown>>;
        const rawEdges = (pj.edges ?? []) as Array<Record<string, unknown>>;
        const ns: ThumbNode[] = rawNodes.map((n) => ({
          id: String(n.id),
          block_id: String(n.block_id ?? ""),
          display_label: typeof n.display_label === "string" ? n.display_label : undefined,
          position: (n.position as { x: number; y: number }) ?? { x: 0, y: 0 },
          isVerdict: n.block_id === "block_step_check",
        }));
        // Fallback auto-layout if positions are all degenerate
        const allZero = ns.every(n => n.position.x === 0 && n.position.y === 0);
        if (allZero && ns.length > 0) autoLayoutLR(ns);
        setNodes(ns);
        setEdges(rawEdges.map((e) => {
          const from = e.from as { node?: string } | string;
          const to = e.to as { node?: string } | string;
          return {
            from: typeof from === "string" ? from : String(from?.node ?? ""),
            to: typeof to === "string" ? to : String(to?.node ?? ""),
          };
        }));
      })
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [pipelineId]);

  const layout = useMemo(() => {
    if (nodes.length === 0) return null;
    const xs = nodes.map(n => n.position.x);
    const ys = nodes.map(n => n.position.y);
    const minX = Math.min(...xs);
    const minY = Math.min(...ys);
    const maxX = Math.max(...xs);
    const maxY = Math.max(...ys);
    return {
      minX: minX - PAD,
      minY: minY - PAD,
      w: (maxX - minX) + NW + PAD * 2,
      h: (maxY - minY) + NH + PAD * 2,
    };
  }, [nodes]);

  if (!pipelineId) {
    return <Placeholder text="尚未綁定 Pipeline" hint="點下方按鈕用 Pipeline Builder 編譯" />;
  }
  if (loading) return <Placeholder text="載入 pipeline…" />;
  if (error) return <Placeholder text={`載入失敗：${error}`} variant="error" />;
  if (!layout || nodes.length === 0) return <Placeholder text="Pipeline 沒有 nodes" />;

  return (
    <div style={{
      background: "#fafbfc",
      border: "1px solid #e5e8eb",
      borderRadius: 10,
      padding: 12,
      height,
      overflow: "hidden",
    }}>
      <svg
        viewBox={`${layout.minX} ${layout.minY} ${layout.w} ${layout.h}`}
        style={{ width: "100%", height: "100%" }}
        preserveAspectRatio="xMidYMid meet"
      >
        <defs>
          <marker id="pst-arrow" viewBox="0 0 10 10" refX="9" refY="5"
                  markerWidth="6" markerHeight="6" orient="auto">
            <path d="M0,0 L10,5 L0,10 z" fill="#94a3b8" />
          </marker>
        </defs>
        {edges.map((e, i) => {
          const from = nodes.find(n => n.id === e.from);
          const to = nodes.find(n => n.id === e.to);
          if (!from || !to) return null;
          const x1 = from.position.x + NW;
          const y1 = from.position.y + NH / 2;
          const x2 = to.position.x;
          const y2 = to.position.y + NH / 2;
          const mx = (x1 + x2) / 2;
          return (
            <path key={i}
                  d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`}
                  stroke="#94a3b8" strokeWidth="1.4" fill="none"
                  markerEnd="url(#pst-arrow)" />
          );
        })}
        {nodes.map(n => {
          const fill = n.isVerdict ? "#fef3c7" : "#ffffff";
          const stroke = n.isVerdict ? "#f59e0b" : "#cbd5e1";
          const labelRaw = (n.display_label || n.block_id).replace(/^block_/, "");
          const label = labelRaw.length > 22 ? labelRaw.slice(0, 20) + "…" : labelRaw;
          return (
            <g key={n.id} transform={`translate(${n.position.x},${n.position.y})`}>
              <rect width={NW} height={NH} rx="8" ry="8"
                    fill={fill} stroke={stroke} strokeWidth="1.4" />
              <text x={NW / 2} y={NH / 2 + 4}
                    textAnchor="middle"
                    fontFamily="'IBM Plex Sans', system-ui, sans-serif"
                    fontSize="11" fontWeight="600"
                    fill={n.isVerdict ? "#92400e" : "#0f172a"}>
                {label}
              </text>
              {n.isVerdict && (
                <text x="9" y="15" fontSize="10" fontWeight="700" fill="#92400e">
                  ⚑
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/** Simple LR auto-layout when pipeline_json has no positions. */
function autoLayoutLR(ns: ThumbNode[]): void {
  ns.forEach((n, i) => {
    n.position = { x: i * (NW + 60), y: 60 };
  });
}

function Placeholder({ text, hint, variant }: { text: string; hint?: string; variant?: "error" }) {
  const errorStyle = variant === "error";
  return (
    <div style={{
      background: errorStyle ? "#fef3f2" : "#fafbfc",
      border: `1px dashed ${errorStyle ? "#fecaca" : "#cbd5e1"}`,
      borderRadius: 10,
      padding: "44px 22px",
      textAlign: "center",
      color: errorStyle ? "#b42318" : "#64748b",
      fontSize: 13,
    }}>
      <div style={{ fontWeight: 600 }}>{text}</div>
      {hint && <div style={{ fontSize: 12, marginTop: 6, opacity: .8 }}>{hint}</div>}
    </div>
  );
}
