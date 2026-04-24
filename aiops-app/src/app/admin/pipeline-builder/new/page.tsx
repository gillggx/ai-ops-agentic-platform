"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import type { PipelineJSON } from "@/lib/pipeline-builder/types";

// React Flow can't SSR
const BuilderLayout = dynamic(() => import("@/components/pipeline-builder/BuilderLayout"), {
  ssr: false,
});

type Kind = "auto_patrol" | "auto_check" | "skill";

export default function NewPipelinePage() {
  const [kind, setKind] = useState<Kind | null>(null);
  // Phase 5: ephemeral pipeline hydrated from Copilot's Edit-in-Builder button
  const [ephemeralPipeline, setEphemeralPipeline] = useState<PipelineJSON | null>(null);
  const [checkedSession, setCheckedSession] = useState(false);

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem("pb:ephemeral_pipeline");
      if (raw) {
        const payload = JSON.parse(raw) as { pipeline_json?: PipelineJSON; ts?: number };
        if (payload?.pipeline_json) {
          setEphemeralPipeline(payload.pipeline_json);
          setKind("skill");  // chat-built pipelines default to skill
        }
        sessionStorage.removeItem("pb:ephemeral_pipeline");
      }
    } catch {
      // ignore malformed payload
    }
    // Deep-link from Triggers Overview: ?kind=auto_check skips the gate.
    // Read from window.location (CSR-only) — useSearchParams would force
    // a Suspense boundary at prerender time.
    if (typeof window !== "undefined") {
      const q = new URLSearchParams(window.location.search).get("kind");
      if (q === "auto_patrol" || q === "auto_check" || q === "skill") {
        setKind(q);
      }
    }
    setCheckedSession(true);
  }, []);

  if (!checkedSession) return null;

  if (kind) {
    return <BuilderLayout mode="new" initialKind={kind} initialPipelineJson={ephemeralPipeline ?? undefined} />;
  }

  return (
    <div
      style={{
        padding: 40,
        maxWidth: 1100,
        margin: "40px auto",
        fontFamily: "system-ui, -apple-system, sans-serif",
      }}
    >
      <h1 style={{ fontSize: 22, color: "#0F172A", marginBottom: 6 }}>建立新 Pipeline</h1>
      <div style={{ fontSize: 13, color: "#64748B", marginBottom: 24 }}>
        先選 Pipeline 類型 — 不同類型有不同結構檢查 + 發佈路徑。建立後仍可在 draft / validating 階段切換類型，lock / active 之後要 clone 才能改。
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14 }}>
        <KindCard
          emoji="🔍"
          label="Auto Patrol"
          tagline="定時巡檢 → 觸發即發 Alarm"
          bullets={[
            "結構需含 block_alert（必要終點）",
            "發佈後由 Cron 排程自動執行",
            "掃全機台、不需 inputs",
            "常用於：機台巡檢 / SPC OOC 監控",
          ]}
          accent="#B45309"
          onPick={() => setKind("auto_patrol")}
        />
        <KindCard
          emoji="⚡"
          label="Auto-Check"
          tagline="Alarm 觸發 → 自動帶入 alarm 資訊跑分析"
          bullets={[
            "結構需含 block_alert 或 block_chart",
            "**必須宣告 inputs**（alarm payload 依名稱自動填入）",
            "發佈後綁定 alarm event_type",
            "常用於：OOC 後自動診斷、recipe drift 後自動畫圖",
          ]}
          accent="#7C3AED"
          onPick={() => setKind("auto_check")}
        />
        <KindCard
          emoji="🩺"
          label="Skill"
          tagline="Agent / User on-demand → 吐圖吐表"
          bullets={[
            "結構需含 block_chart（必要終點）",
            "禁止含 block_alert",
            "發佈後註冊進 Agent Skill Registry",
            "常用於：Agent 對話中調用查資料",
          ]}
          accent="#166534"
          onPick={() => setKind("skill")}
        />
      </div>
    </div>
  );
}

function KindCard({
  emoji,
  label,
  tagline,
  bullets,
  accent,
  onPick,
}: {
  emoji: string;
  label: string;
  tagline: string;
  bullets: string[];
  accent: string;
  onPick: () => void;
}) {
  return (
    <button
      onClick={onPick}
      style={{
        textAlign: "left",
        padding: 18,
        border: `1px solid #E2E8F0`,
        borderRadius: 8,
        background: "#fff",
        cursor: "pointer",
        fontFamily: "inherit",
        transition: "border-color 120ms, box-shadow 120ms",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = accent;
        e.currentTarget.style.boxShadow = `0 2px 6px rgba(0,0,0,0.04)`;
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = "#E2E8F0";
        e.currentTarget.style.boxShadow = "none";
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
        <span style={{ fontSize: 26 }}>{emoji}</span>
        <span style={{ fontSize: 16, fontWeight: 700, color: "#0F172A" }}>{label}</span>
      </div>
      <div style={{ fontSize: 12, color: accent, fontWeight: 600, marginBottom: 10 }}>{tagline}</div>
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: "#475569", lineHeight: 1.7 }}>
        {bullets.map((b, i) => (
          <li key={i}>{b}</li>
        ))}
      </ul>
    </button>
  );
}
