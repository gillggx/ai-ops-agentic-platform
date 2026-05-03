"use client";

import dynamic from "next/dynamic";

const TopologyWorkbench = dynamic(
  () => import("@/components/ontology/topology-v2/TopologyWorkbench"),
  {
    ssr: false,
    loading: () => (
      <div className="micro" style={{ padding: 24, textAlign: "center", color: "var(--c-ink-3)" }}>
        載入拓樸 Workbench…
      </div>
    ),
  },
);

/** Embeds the TopologyWorkbench on the EQP detail page, focused on this tool. */
export function TopologyTab({ toolId }: { toolId: string }) {
  return (
    <div
      className="surface"
      style={{ minHeight: 640, height: 640, display: "flex", flexDirection: "column", overflow: "hidden" }}
    >
      <TopologyWorkbench
        mode="embedded"
        initialFocus={{ kind: "tool", id: toolId }}
      />
    </div>
  );
}
