"use client";

/** 10-bucket histogram for cluster alarm density. Height proportional to
 *  max bucket so a quiet cluster + a noisy cluster look distinct without
 *  needing a y-axis. */
export function Sparkline({ values, width = 60, height = 16 }: {
  values: number[];
  width?: number;
  height?: number;
}) {
  const max = Math.max(1, ...values);
  const barW = width / values.length;
  return (
    <svg width={width} height={height} className="sparkline" aria-hidden>
      {values.map((v, i) => {
        const h = Math.max(1, (v / max) * height);
        return (
          <rect
            key={i}
            className="sparkline__bar"
            x={i * barW + 0.5}
            y={height - h}
            width={Math.max(1, barW - 1)}
            height={h}
            rx={1}
          />
        );
      })}
    </svg>
  );
}
