"use client";

import { useEffect, useRef } from "react";

interface Props {
  spec: Record<string, unknown>;
}

export function VegaLiteChart({ spec }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    let cancelled = false;

    import("vega-embed").then(({ default: vegaEmbed }) => {
      if (cancelled || !containerRef.current) return;
      // Inject container width so "width":"container" works correctly
      const specWithWidth = {
        ...spec,
        width: "container",
        background: "white",
      };
      vegaEmbed(containerRef.current, specWithWidth as never, {
        actions: { export: true, source: false, compiled: false, editor: false },
        renderer: "svg",
      }).catch((err) => {
        console.error("[VegaLiteChart] render error:", err);
      });
    });

    return () => { cancelled = true; };
  }, [spec]);

  return (
    <div
      ref={containerRef}
      style={{
        width: "100%",
        minHeight: 200,
        background: "white",
        borderRadius: 8,
        overflow: "hidden",
      }}
    />
  );
}
