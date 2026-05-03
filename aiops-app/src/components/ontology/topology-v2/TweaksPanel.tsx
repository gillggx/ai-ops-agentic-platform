"use client";

import { TweaksState } from "./lib/types";

interface Props {
  state:    TweaksState;
  onChange: (next: TweaksState) => void;
  onClose:  () => void;
}

export default function TweaksPanel({ state, onChange, onClose }: Props) {
  const set = <K extends keyof TweaksState>(k: K, v: TweaksState[K]) => onChange({ ...state, [k]: v });

  return (
    <div style={{
      position: "absolute", bottom: 96, right: 14, width: 240,
      background: "#fff", border: "1px solid #e0e0e0", borderRadius: 4,
      boxShadow: "0 8px 24px rgba(0,0,0,0.10)", padding: "12px 14px",
      fontSize: 11, color: "#222", zIndex: 20,
    }}>
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        marginBottom: 10,
      }}>
        <div style={{ fontWeight: 600, color: "#111", letterSpacing: "0.06em", fontSize: 11 }}>
          TWEAKS
        </div>
        <button onClick={onClose} style={{
          border: "none", background: "transparent", color: "#999",
          cursor: "pointer", fontSize: 16, padding: 0, fontFamily: "inherit", lineHeight: 1,
        }}>×</button>
      </div>

      <Section label="Anomaly emphasis">
        <Radio value={state.anomalyEmph} onChange={(v) => set("anomalyEmph", v)}
               options={[
                 { value: "none",   label: "None"   },
                 { value: "subtle", label: "Subtle" },
                 { value: "strong", label: "Strong" },
               ]} />
      </Section>

      <Section label="Lane links">
        <Radio value={state.linkStyle} onChange={(v) => set("linkStyle", v)}
               options={[
                 { value: "underline", label: "Underline" },
                 { value: "border",    label: "Border"    },
                 { value: "tint",      label: "Tint"      },
               ]} />
      </Section>
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "#999", marginBottom: 4, textTransform: "uppercase" }}>
        {label}
      </div>
      {children}
    </div>
  );
}

function Radio<T extends string>({ value, onChange, options }: {
  value: T; onChange: (v: T) => void; options: { value: T; label: string }[];
}) {
  return (
    <div style={{ display: "flex", gap: 4 }}>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            onClick={() => onChange(o.value)}
            style={{
              flex: 1, padding: "4px 8px",
              border: `1px solid ${active ? "#111" : "#e0e0e0"}`,
              background: active ? "#111" : "#fff",
              color: active ? "#fff" : "#444",
              fontSize: 10, fontWeight: active ? 600 : 500,
              borderRadius: 2, cursor: "pointer", fontFamily: "inherit",
              letterSpacing: "0.04em",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
