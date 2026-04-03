interface KpiSpec {
  label: string;
  value: number | string;
  unit?: string;
  trend?: "up" | "down" | "stable";
}

interface Props {
  spec: Record<string, unknown>;
}

const TREND_SYMBOL: Record<string, string> = { up: "↑", down: "↓", stable: "→" };
const TREND_COLOR: Record<string, string> = { up: "#fc8181", down: "#68d391", stable: "#90cdf4" };

export function KpiCard({ spec }: Props) {
  const { label, value, unit, trend } = spec as unknown as KpiSpec;
  return (
    <div style={{
      background: "#1a202c",
      border: "1px solid #2d3748",
      borderRadius: 8,
      padding: "16px 24px",
      display: "inline-block",
      minWidth: 140,
    }}>
      <div style={{ fontSize: 12, color: "#718096", marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 28, fontWeight: 700, color: "#e2e8f0" }}>
        {value}
        {unit && <span style={{ fontSize: 14, marginLeft: 4, color: "#718096" }}>{unit}</span>}
        {trend && (
          <span style={{ fontSize: 16, marginLeft: 8, color: TREND_COLOR[trend] ?? "#e2e8f0" }}>
            {TREND_SYMBOL[trend]}
          </span>
        )}
      </div>
    </div>
  );
}
