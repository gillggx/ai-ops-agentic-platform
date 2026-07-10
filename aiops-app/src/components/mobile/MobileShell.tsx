"use client";

/**
 * MobileShell (2026-07-11) — 手機版殼層，viewport ≤ 767px 時由 AppShell 啟用。
 *
 * 底部 4 tab：對話（agent 主畫面）/ 總覽 / Skills / 手冊。
 * 總覽可下鑽：全廠總覽 1c → 設備詳情 1d；Open alarms → 告警戰情 1a → 1b。
 * 對話 tab 直接掛既有 AIAgentPanel（保持 mounted，切 tab 不清對話）。
 * 右下 ✦ 浮鈕（非對話 tab）一鍵回到 agent。
 */
import { useState } from "react";
import { ensurePlexFont } from "@/components/skills-v2/tokens";
import { useEffect } from "react";
import { M } from "./tokens";
import { MobileOverview } from "./MobileOverview";
import { MobileAlarms, type MobileCluster } from "./MobileAlarms";
import { MobileAlarmDetail } from "./MobileAlarmDetail";
import { MobileEqpDetail } from "./MobileEqpDetail";
import { MobileSkills } from "./MobileSkills";
import { MobileManual } from "./MobileManual";

type Tab = "chat" | "overview" | "skills" | "manual";
type Drill =
  | { kind: "none" }
  | { kind: "alarms" }
  | { kind: "cluster"; cluster: MobileCluster }
  | { kind: "eqp"; id: string };

const TABS: Array<{ key: Tab; label: string; icon: string }> = [
  { key: "chat", label: "對話", icon: "✦" },
  { key: "overview", label: "總覽", icon: "▦" },
  { key: "skills", label: "Skills", icon: "◆" },
  { key: "manual", label: "手冊", icon: "▤" },
];

export function MobileShell({ agentPanel }: { agentPanel: React.ReactNode }) {
  const [tab, setTab] = useState<Tab>("chat");
  const [drill, setDrill] = useState<Drill>({ kind: "none" });

  useEffect(() => { ensurePlexFont(); }, []);

  const overviewBody = drill.kind === "alarms" ? (
    <MobileAlarms onOpenCluster={(cluster) => setDrill({ kind: "cluster", cluster })} />
  ) : drill.kind === "cluster" ? (
    <MobileAlarmDetail cluster={drill.cluster} onBack={() => setDrill({ kind: "alarms" })} />
  ) : drill.kind === "eqp" ? (
    <MobileEqpDetail id={drill.id}
      onBack={() => setDrill({ kind: "none" })}
      onSwitch={(id) => setDrill({ kind: "eqp", id })} />
  ) : (
    <MobileOverview
      onOpenEqp={(id) => setDrill({ kind: "eqp", id })}
      onOpenAlarms={() => setDrill({ kind: "alarms" })} />
  );

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 40, display: "flex", flexDirection: "column",
      background: M.bg, fontFamily: M.sans,
    }}>
      {/* content */}
      <div style={{ flex: 1, overflow: "hidden", position: "relative" }}>
        {/* 對話 keep-mounted：切 tab 不清對話（display 切換） */}
        <div style={{
          position: "absolute", inset: 0, display: tab === "chat" ? "flex" : "none",
          flexDirection: "column", background: "var(--pn, #fff)",
        }}>
          <div style={{
            padding: "10px 14px", borderBottom: `1px solid ${M.line}`,
            display: "flex", alignItems: "center", gap: 9, background: "var(--pn, #fff)",
          }}>
            <span style={{
              width: 30, height: 30, borderRadius: 9, background: "var(--p, #1E5A44)",
              color: "#fff", display: "flex", alignItems: "center", justifyContent: "center",
              fontWeight: 800, fontSize: 14,
            }}>A</span>
            <div>
              <div style={{ fontSize: 13.5, fontWeight: 800, color: M.ink }}>AI Agent</div>
              <div style={{ fontSize: 10, color: M.ok }}>ChatOps ・ 線上</div>
            </div>
          </div>
          <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
            {agentPanel}
          </div>
        </div>

        {tab === "overview" && (
          <div style={{ position: "absolute", inset: 0, overflowY: "auto" }}>{overviewBody}</div>
        )}
        {tab === "skills" && (
          <div style={{ position: "absolute", inset: 0, overflowY: "auto" }}><MobileSkills /></div>
        )}
        {tab === "manual" && (
          <div style={{ position: "absolute", inset: 0, overflowY: "auto" }}><MobileManual /></div>
        )}

        {/* ✦ 問 agent 浮鈕（非對話 tab） */}
        {tab !== "chat" && (
          <button onClick={() => setTab("chat")} style={{
            position: "absolute", right: 16, bottom: 18, width: 54, height: 54,
            borderRadius: "50%", border: "none", cursor: "pointer",
            background: "#5C1F35", color: "#f5d9e6", fontSize: 22,
            boxShadow: "0 8px 22px -8px rgba(20,23,60,.45)",
          }}>✦</button>
        )}
      </div>

      {/* bottom tab bar */}
      <div style={{
        display: "flex", borderTop: `1px solid ${M.line}`, background: "#fff",
        paddingBottom: "env(safe-area-inset-bottom, 0px)", flexShrink: 0,
      }}>
        {TABS.map((t) => {
          const on = tab === t.key;
          return (
            <button key={t.key}
              onClick={() => { setTab(t.key); if (t.key === "overview") setDrill({ kind: "none" }); }}
              style={{
                flex: 1, border: "none", background: "none", cursor: "pointer",
                padding: "8px 0 7px", display: "flex", flexDirection: "column",
                alignItems: "center", gap: 2,
              }}>
              <span style={{ fontSize: 17, color: on ? "var(--p, #1E5A44)" : "#a0a4b5" }}>{t.icon}</span>
              <span style={{
                fontSize: 10, fontWeight: on ? 800 : 500,
                color: on ? "var(--p, #1E5A44)" : "#8b90a7",
              }}>{t.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
