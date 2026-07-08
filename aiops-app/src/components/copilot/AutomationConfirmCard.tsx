"use client";

/**
 * AutomationConfirmCard (草稿暫存區 P3b, 2026-07-09).
 *
 * The agent parsed a chat sentence like「每小時巡檢，超過 3 次 OOC 就告警」into
 * an automation config and proposed it here. NOTHING is live yet — the human
 * confirms in this authed card, and only then does the FRONTEND run the enable
 * (create skill → apply automation → activate) via the tested skills_v2
 * endpoints. Java's saveAutomation is the readiness source of truth (e.g.
 * patrol needs an alarm judgment) — any rejection is surfaced honestly here,
 * never faked.
 */
import { useState } from "react";

export interface AutomationConfig {
  role: "patrol" | "datacheck";
  trigger: { kind: "schedule"; schedule: string };
  alarm_gate?: string;
  outcome?: string;
  summary?: string;
}

export interface AutomationConfirmData {
  config: AutomationConfig;
  pipeline_json: Record<string, unknown>;
}

const ROLE_LABEL: Record<string, string> = {
  patrol: "自動巡檢（Auto Patrol）",
  datacheck: "自動檢查（Auto Check）",
};

export function AutomationConfirmCard({ data }: { data: AutomationConfirmData }) {
  const [cfg, setCfg] = useState<AutomationConfig>(data.config);
  const [state, setState] = useState<"idle" | "working" | "done" | "error">("idle");
  const [msg, setMsg] = useState<string>("");
  const [slug, setSlug] = useState<string>("");

  const pjName = (data.pipeline_json?.name as string) || cfg.summary || "Chat 自動化";

  const confirm = async () => {
    setState("working"); setMsg("");
    try {
      // 1. create the skill (draft) from the on-screen pipeline
      const c = await fetch("/api/skills-v2/with-pipeline", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: pjName, nl: cfg.summary ?? "", sub: (cfg.summary ?? "").slice(0, 60),
          pipeline_json: data.pipeline_json, pipeline_kind: "skill",
        }),
      });
      const cEnv = await c.json();
      if (!c.ok) throw new Error(cEnv?.error?.message || "建立 Skill 失敗");
      const sk = (cEnv?.data ?? cEnv)?.skill;
      const sl = sk?.slug as string;
      if (!sl) throw new Error("建立 Skill 後找不到 slug");
      setSlug(String(sk?.id ?? sl));
      // 2. apply automation (Java validates readiness — e.g. patrol needs alarm)
      const a = await fetch(`/api/skills-v2/${encodeURIComponent(sl)}/automation`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          role: cfg.role, trigger: cfg.trigger,
          ...(cfg.role === "patrol" ? { alarm_gate: cfg.alarm_gate, outcome: cfg.outcome } : {}),
        }),
      });
      const aEnv = await a.json();
      if (!a.ok) throw new Error(aEnv?.error?.message || "套用自動化失敗");
      // 3. activate (draft → active, joins the scheduler)
      const act = await fetch(`/api/skills-v2/${encodeURIComponent(sl)}/activate`, { method: "POST" });
      if (!act.ok) {
        const e = await act.json().catch(() => ({}));
        throw new Error(e?.error?.message || "啟用失敗");
      }
      setState("done");
      setMsg(`已啟用「${pjName}」，${ROLE_LABEL[cfg.role]} · ${cfg.trigger.schedule} 開始排程。`);
    } catch (e) {
      setState("error");
      setMsg(e instanceof Error ? e.message : "啟用失敗");
    }
  };

  const line: React.CSSProperties = { display: "flex", gap: 8, fontSize: 12.5, color: "#334155" };
  const key: React.CSSProperties = { color: "#64748B", flex: "0 0 74px" };

  return (
    <div style={{ maxWidth: 420, border: "1px solid #E2E8F0", borderRadius: 12, overflow: "hidden", background: "#fff" }}>
      <div style={{ padding: "12px 15px", borderBottom: "1px solid #EEF2F6", background: "#F8FAFC" }}>
        <div style={{ fontSize: 13.5, fontWeight: 700 }}>設定自動化 · 確認後才上線</div>
        <div style={{ fontSize: 11.5, color: "#64748B", marginTop: 2 }}>{cfg.summary || "把這張圖設成自動執行"}</div>
      </div>
      <div style={{ padding: "13px 15px", display: "flex", flexDirection: "column", gap: 9 }}>
        <div style={line}><span style={key}>角色</span>
          <select value={cfg.role} disabled={state !== "idle"}
            onChange={(e) => setCfg({ ...cfg, role: e.target.value as AutomationConfig["role"] })}
            style={{ font: "inherit", border: "1px solid #E2E8F0", borderRadius: 6, padding: "3px 7px" }}>
            <option value="patrol">自動巡檢（Auto Patrol）</option>
            <option value="datacheck">自動檢查（Auto Check）</option>
          </select>
        </div>
        <div style={line}><span style={key}>排程</span>
          <select value={cfg.trigger.schedule} disabled={state !== "idle"}
            onChange={(e) => setCfg({ ...cfg, trigger: { ...cfg.trigger, schedule: e.target.value } })}
            style={{ font: "inherit", border: "1px solid #E2E8F0", borderRadius: 6, padding: "3px 7px" }}>
            {["每 15 分鐘", "每 30 分鐘", "每 1 小時", "每 3 小時", "每天 08:00", "每天 20:00"].map((s) =>
              <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        {cfg.role === "patrol" && (
          <>
            <div style={line}><span style={key}>告警條件</span><span style={{ color: "#334155" }}>{cfg.alarm_gate || "（未指定）"}</span></div>
            <div style={line}><span style={key}>命中處理</span><span style={{ color: "#334155" }}>{cfg.outcome || "告警"}</span></div>
            <div style={{ fontSize: 11, color: "#B45309", background: "#FFFBEB", border: "1px solid #FDE68A",
              borderRadius: 7, padding: "6px 9px" }}>
              巡檢需要 pipeline 內含「告警判斷式」。若這張圖沒有，啟用會被擋 —— 屆時到編輯器補一個條件再試。
            </div>
          </>
        )}
      </div>
      {msg && (
        <div style={{ padding: "0 15px 6px", fontSize: 12,
          color: state === "error" ? "#B91C1C" : "#047857" }}>{msg}</div>
      )}
      <div style={{ padding: "11px 15px", borderTop: "1px solid #EEF2F6", display: "flex", justifyContent: "flex-end", gap: 8 }}>
        {state === "done" ? (
          slug && <a href={`/skills/${slug}`} target="_blank" rel="noreferrer"
            style={{ fontSize: 12.5, padding: "7px 15px", borderRadius: 8, background: "#4F46E5", color: "#fff",
              fontWeight: 700, textDecoration: "none" }}>開啟 Skill</a>
        ) : (
          <button onClick={confirm} disabled={state === "working"}
            style={{ fontSize: 12.5, padding: "7px 16px", borderRadius: 8, border: "none",
              background: "#4F46E5", color: "#fff", fontWeight: 700, cursor: "pointer" }}>
            {state === "working" ? "啟用中…" : "確認啟用"}
          </button>
        )}
      </div>
    </div>
  );
}
