"use client";

/**
 * 手機 4b Skills — 清單卡直排＋類型篩選膠囊。動作連到既有 /skills/[slug] 頁。
 */
import { useEffect, useMemo, useState } from "react";
import { M, cardStyle } from "./tokens";

interface Skill {
  id: number; slug: string; name: string; sub: string; nl: string;
  role: "tool" | "patrol" | "datacheck"; status: string;
  in_type: string; out_type: string; trigger_config: string | null;
}

const ROLE_BADGE: Record<string, { label: string; fg: string; bg: string }> = {
  patrol: { label: "Auto Patrol", fg: "#92400e", bg: "#fef3c7" },
  datacheck: { label: "Data Check", fg: "#1d4ed8", bg: "#dbeafe" },
  tool: { label: "工具", fg: "#5b6070", bg: "#f1f2f7" },
};

function triggerSummary(s: Skill): string {
  if (!s.trigger_config) return s.role === "tool" ? "未綁定 trigger" : "";
  try {
    const t = JSON.parse(s.trigger_config);
    if (t?.kind === "schedule" || t?.type === "schedule") {
      return `排程 ${t.every ?? t.cron ?? ""}`.trim();
    }
    if (t?.kind === "event" || t?.type === "event") {
      return `on event ${t.event ?? t.event_type ?? ""}`.trim();
    }
  } catch { /* opaque config */ }
  return "";
}

export function MobileSkills() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [chip, setChip] = useState<"all" | "patrol" | "datacheck" | "tool">("all");

  useEffect(() => {
    fetch("/api/skills-v2", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((env) => {
        const d = env?.data ?? env;
        if (Array.isArray(d)) setSkills(d as Skill[]);
      })
      .catch(() => { /* ambient */ });
  }, []);

  const counts = useMemo(() => ({
    patrol: skills.filter((s) => s.role === "patrol").length,
    datacheck: skills.filter((s) => s.role === "datacheck").length,
    tool: skills.filter((s) => s.role === "tool").length,
  }), [skills]);
  const shown = skills.filter((s) => chip === "all" || s.role === chip);

  return (
    <div style={{ padding: "14px 14px 90px", fontFamily: M.sans, color: M.ink }}>
      <div style={{ display: "flex", alignItems: "center" }}>
        <span style={{ fontSize: 21, fontWeight: 800 }}>Skills</span>
        <span style={{ flex: 1 }} />
        <a href="/skills" style={{
          fontSize: 12, fontWeight: 700, color: "var(--p, #1E5A44)", textDecoration: "none",
        }}>桌機完整版 ›</a>
      </div>
      <div style={{ fontSize: 11.5, color: M.sub, marginTop: 3 }}>
        自然語言描述、編譯成 data pipeline 的可重用工具
      </div>

      <div style={{ display: "flex", gap: 7, margin: "12px 0 10px", overflowX: "auto" }}>
        {([["all", `全部 ${skills.length}`], ["patrol", `Auto Patrol ${counts.patrol}`],
           ["datacheck", `Data Check ${counts.datacheck}`], ["tool", `工具 ${counts.tool}`]] as const).map(([k, label]) => (
          <button key={k} onClick={() => setChip(k)} style={{
            flexShrink: 0, border: "none", borderRadius: 16, padding: "6px 12px",
            fontSize: 12, fontWeight: 700, cursor: "pointer",
            background: chip === k ? M.ink : "#fff",
            color: chip === k ? "#fff" : M.sub,
            boxShadow: chip === k ? "none" : `inset 0 0 0 1px ${M.line}`,
          }}>{label}</button>
        ))}
      </div>

      {shown.map((s) => {
        const badge = ROLE_BADGE[s.role] ?? ROLE_BADGE.tool;
        const active = s.status === "active";
        const dot = active ? M.ok : s.status === "draft" ? M.med : M.faint;
        const trig = triggerSummary(s);
        return (
          <div key={s.slug} style={{ ...cardStyle, padding: "12px 13px", marginBottom: 9 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: dot, flexShrink: 0 }} />
              <span style={{ fontSize: 13.5, fontWeight: 700, flex: 1, minWidth: 120 }}>{s.name}</span>
              <span style={{
                fontSize: 9, fontWeight: 700, fontFamily: M.mono, padding: "1px 7px",
                borderRadius: 4, color: badge.fg, background: badge.bg,
              }}>{badge.label}</span>
              <span style={{
                fontSize: 9, fontWeight: 700, fontFamily: M.mono, padding: "1px 7px", borderRadius: 4,
                color: active ? M.ok : M.med, background: active ? M.okBg : M.medBg,
              }}>{active ? "運行中" : "草稿"}</span>
            </div>
            {(s.sub || s.nl) && (
              <div style={{
                fontSize: 12, color: M.sub, marginTop: 6, lineHeight: 1.5,
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
              }}>{s.sub || s.nl}</div>
            )}
            <div style={{ fontFamily: M.mono, fontSize: 10.5, color: M.faint, marginTop: 5 }}>
              in: {s.in_type || "—"} → out: {s.out_type || "—"}{trig ? ` ・ ${trig}` : ""}
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 9 }}>
              <a href={`/skills/${encodeURIComponent(s.slug)}`} style={btn(false)}>編寫</a>
              <a href={`/skills/${encodeURIComponent(s.slug)}/automate`} style={btn(true)}>
                {s.role === "tool" ? "設定自動化" : "編輯自動化"}
              </a>
            </div>
          </div>
        );
      })}
      {shown.length === 0 && (
        <div style={{ padding: 24, textAlign: "center", color: M.faint, fontSize: 12.5 }}>沒有符合的 Skill</div>
      )}
    </div>
  );
}

function btn(primary: boolean): React.CSSProperties {
  return {
    flex: 1, textAlign: "center", padding: "8px 0", borderRadius: 9,
    fontSize: 12, fontWeight: 700, textDecoration: "none",
    background: primary ? "var(--p, #1E5A44)" : "#fff",
    color: primary ? "#fff" : M.sub,
    boxShadow: primary ? "none" : `inset 0 0 0 1px ${M.line}`,
  };
}
