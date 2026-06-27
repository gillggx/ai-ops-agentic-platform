"use client";

import type { PatrolFunnel } from "./types";

interface Props {
  funnel: PatrolFunnel | null;
}

/**
 * Five chips reading left-to-right as a funnel:
 *   Events → Skill Runs → Step Passed → Alarms (+ Dedup-suppressed)
 *
 * Dedup-suppressed is rendered as a side-note on the Alarms chip because
 * it explains "this many WOULD have alarmed but didn't" — keeping it on
 * the alarms tile avoids implying it's a separate funnel branch.
 */
export function PatrolFunnelSummary({ funnel }: Props) {
  if (!funnel) {
    return (
      <div style={containerStyle}>
        <div style={{ ...chipStyle, color: "#a0aec0", fontStyle: "italic" }}>計算中...</div>
      </div>
    );
  }

  return (
    <div style={containerStyle}>
      <Chip label="Events" value={funnel.events} hint="從 simulator 進來" />
      <Arrow />
      <Chip label="Skill Runs" value={funnel.skillRuns} hint="auto-check 觸發數" />
      <Arrow />
      <Chip label="Step Passed" value={funnel.stepPassed} hint="≥1 step pass" />
      <Arrow />
      <Chip
        label="Alarms"
        value={funnel.alarms}
        hint={
          funnel.dedupSuppressed > 0
            ? `+${funnel.dedupSuppressed} 被 dedup 擋`
            : "AlarmEmitter 已寫入"
        }
        accent="primary"
      />
    </div>
  );
}

function Chip({ label, value, hint, accent }: {
  label: string;
  value: number;
  hint?: string;
  accent?: "primary";
}) {
  const isPrimary = accent === "primary";
  return (
    <div style={{
      flex: 1,
      background: isPrimary ? "#ebf8ff" : "#fff",
      border: `1px solid ${isPrimary ? "#bee3f8" : "#e2e8f0"}`,
      borderRadius: 8,
      padding: "10px 14px",
      minWidth: 120,
    }}>
      <div style={{ fontSize: 10, color: "#718096", textTransform: "uppercase", letterSpacing: "0.5px", fontWeight: 700 }}>
        {label}
      </div>
      <div style={{ fontSize: 24, fontWeight: 700, color: isPrimary ? "#2b6cb0" : "#1a202c", marginTop: 2 }}>
        {value.toLocaleString()}
      </div>
      {hint && (
        <div style={{ fontSize: 10, color: "#a0aec0", marginTop: 2 }}>{hint}</div>
      )}
    </div>
  );
}

function Arrow() {
  return (
    <div style={{ color: "#cbd5e0", fontSize: 18, fontWeight: 400, alignSelf: "center" }}>→</div>
  );
}

const containerStyle: React.CSSProperties = {
  display: "flex",
  gap: 8,
  alignItems: "stretch",
};

const chipStyle: React.CSSProperties = {
  flex: 1,
  background: "#fff",
  border: "1px solid #e2e8f0",
  borderRadius: 8,
  padding: "10px 14px",
  fontSize: 13,
};
