"use client";

/**
 * AutomationHandoffCard (草稿暫存區 P3b, redesigned 2026-07-09).
 *
 * The bespoke "confirm card" was a窗口 failure: for a vague「幫我開啟」it
 * fabricated a patrol/hourly/no-gate config the agent itself said would be
 * blocked. Automation is set on the SAME page as the Skill Library
 * (/skills/[slug]/automate). So the chat only HANDS OFF: store the on-screen
 * pipeline as a Skill, then open that page — no invented config, no doomed
 * confirm, consistent UX.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";

export interface AutomationHandoffData {
  pipeline_json: Record<string, unknown>;
  /** F2 (2026-07-10): the user's original prompt — persisted as the skill NL
   *  (was silently ""), so the draft skill keeps its provenance. */
  goal?: string;
}

export function AutomationConfirmCard({ data }: { data: AutomationHandoffData }) {
  const router = useRouter();
  const [state, setState] = useState<"idle" | "working" | "error">("idle");
  const [msg, setMsg] = useState("");

  const name = (data.pipeline_json?.name as string) || "Chat 自動化";

  const go = async () => {
    setState("working"); setMsg("");
    try {
      const r = await fetch("/api/skills-v2/with-pipeline", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name, nl: data.goal ?? "", sub: "從對話設定自動化",
          pipeline_json: data.pipeline_json, pipeline_kind: "skill",
        }),
      });
      const env = await r.json();
      if (!r.ok) throw new Error(env?.error?.message || "存成 Skill 失敗");
      const sk = (env?.data ?? env)?.skill;
      const slug = sk?.slug;
      if (!slug) throw new Error("找不到 Skill slug");
      router.push(`/skills/${encodeURIComponent(slug)}/automate`);
    } catch (e) {
      setState("error");
      setMsg(e instanceof Error ? e.message : "失敗");
    }
  };

  return (
    <div style={{ maxWidth: 420, border: "1px solid #E2E8F0", borderRadius: 12, overflow: "hidden", background: "#fff" }}>
      <div style={{ padding: "12px 15px", borderBottom: "1px solid #EEF2F6", background: "var(--pn, #F8FAFC)" }}>
        <div style={{ fontSize: 13.5, fontWeight: 700 }}>設定自動化</div>
        <div style={{ fontSize: 11.5, color: "#64748B", marginTop: 2 }}>
          巡檢 / 定期檢查 / 告警都在 Skill 的設定頁做，跟 Skill 庫一樣。
        </div>
      </div>
      <div style={{ padding: "13px 15px", fontSize: 12.5, color: "#334155" }}>
        我先把「{name}」存成 Skill，再帶你去設定頁——角色、排程、告警條件都在那設，不用先在這裡填。
      </div>
      {msg && <div style={{ padding: "0 15px 8px", fontSize: 12, color: "#B91C1C" }}>{msg}</div>}
      <div style={{ padding: "11px 15px", borderTop: "1px solid #EEF2F6", display: "flex", justifyContent: "flex-end" }}>
        <button onClick={go} disabled={state === "working"}
          style={{ fontSize: 12.5, padding: "7px 16px", borderRadius: 8, border: "none",
            background: "var(--p, #4F46E5)", color: "#fff", fontWeight: 700, cursor: "pointer" }}>
          {state === "working" ? "處理中…" : "存成 Skill 並開設定頁"}
        </button>
      </div>
    </div>
  );
}
