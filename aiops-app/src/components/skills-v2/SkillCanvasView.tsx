"use client";

/**
 * Skills v2 Editor — read-only pipeline canvas.
 *
 * Reuses the SAME stack as chat-mode's Lite Canvas (LiteCanvasOverlay):
 * BuilderProvider + DagCanvas(readOnly) + PipelineThemeStyles, hydrated
 * from a pipeline's pipeline_json. The user sees exactly what the real
 * Pipeline Builder would draw — pan / zoom / click a node to inspect, but
 * no dragging or editing. To edit they click "編輯 pipeline →" which routes
 * into the full PB.
 *
 * Differs from LiteCanvasOverlay: no glass-event stream, no tabs, no run
 * results — it's a static read-only view of an already-saved pipeline,
 * fetched by id once on mount.
 */

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { BuilderProvider, useBuilder } from "@/context/pipeline-builder/BuilderContext";
import { listBlocks } from "@/lib/pipeline-builder/api";
import { autoLayoutPipeline } from "@/lib/pipeline-builder/glass-ops";
import PipelineThemeStyles from "../pipeline-builder/PipelineThemeStyles";
import type { BlockSpec, PipelineJSON } from "@/lib/pipeline-builder/types";

const DagCanvas = dynamic(() => import("@/components/pipeline-builder/DagCanvas"), {
  ssr: false,
});

interface Props {
  pipelineId: number | null;
  height?: number;
}

export default function SkillCanvasView({ pipelineId, height = 460 }: Props) {
  return (
    <BuilderProvider>
      <Inner pipelineId={pipelineId} height={height} />
    </BuilderProvider>
  );
}

function Inner({ pipelineId, height }: Props) {
  const { actions } = useBuilder();
  const [catalog, setCatalog] = useState<BlockSpec[]>([]);
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "empty" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  // Block catalog (DagCanvas needs it for node rendering).
  useEffect(() => {
    let cancel = false;
    (async () => {
      try {
        const b = await listBlocks();
        if (!cancel) setCatalog(b);
      } catch { /* DagCanvas degrades gracefully */ }
    })();
    return () => { cancel = true; };
  }, []);

  // Fetch pipeline_json by id, hydrate the builder, auto-layout if needed.
  useEffect(() => {
    if (!pipelineId) { setStatus("empty"); return; }
    setStatus("loading"); setError(null);
    let cancel = false;
    (async () => {
      try {
        const res = await fetch(`/api/pipeline-builder/pipelines/${pipelineId}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const env = await res.json();
        const record = env?.data ?? env;
        // Java stores pipeline_json as a TEXT column → arrives as a string.
        const rawPj = record?.pipeline_json ?? record;
        let pj: PipelineJSON;
        if (typeof rawPj === "string") pj = JSON.parse(rawPj);
        else pj = rawPj as PipelineJSON;

        if (cancel) return;
        const nodes = pj.nodes ?? [];
        if (nodes.length === 0) { setStatus("empty"); return; }

        // Auto-layout when positions are degenerate (all 0,0) so the DAG
        // isn't stacked on top of itself.
        const allZero = nodes.every(n => !n.position || (n.position.x === 0 && n.position.y === 0));
        const finalNodes = allZero ? autoLayoutPipeline(nodes, pj.edges ?? []) : nodes;

        actions.init({
          pipeline: {
            version: pj.version ?? "1.0",
            name: pj.name ?? "skill pipeline",
            inputs: pj.inputs,
            nodes: finalNodes.length > 0 ? finalNodes : nodes,
            edges: pj.edges ?? [],
            metadata: pj.metadata ?? {},
          },
        });
        setStatus("ready");
      } catch (e) {
        if (!cancel) { setError(e instanceof Error ? e.message : String(e)); setStatus("error"); }
      }
    })();
    return () => { cancel = true; };
  // actions is stable from context; intentionally excluded
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pipelineId]);

  if (status === "empty") {
    return <Placeholder text={pipelineId ? "Pipeline 沒有 nodes" : "尚未綁定 Pipeline"}
                        hint={pipelineId ? undefined : "點下方「用 Pipeline Builder 編譯」建立"} />;
  }
  if (status === "error") return <Placeholder text={`載入失敗：${error}`} variant="error" />;

  return (
    <div
      data-pb-theme="light"
      style={{
        position: "relative", width: "100%", height,
        background: "#FAFAFA", border: "1px solid #e5e8eb", borderRadius: 10,
        overflow: "hidden",
      }}
    >
      <PipelineThemeStyles />
      <DagCanvas blockCatalog={catalog} readOnly autoFit />
      {status === "loading" && (
        <div style={{
          position: "absolute", inset: 0, display: "flex", alignItems: "center",
          justifyContent: "center", color: "#94a3b8", fontSize: 13, background: "#FAFAFA",
        }}>
          載入 pipeline…
        </div>
      )}
    </div>
  );
}

function Placeholder({ text, hint, variant }: { text: string; hint?: string; variant?: "error" }) {
  const err = variant === "error";
  return (
    <div style={{
      background: err ? "#fef3f2" : "#fafbfc",
      border: `1px dashed ${err ? "#fecaca" : "#cbd5e1"}`,
      borderRadius: 10, padding: "48px 22px", textAlign: "center",
      color: err ? "#b42318" : "#64748b", fontSize: 13,
    }}>
      <div style={{ fontWeight: 600 }}>{text}</div>
      {hint && <div style={{ fontSize: 12, marginTop: 6, opacity: .8 }}>{hint}</div>}
    </div>
  );
}
