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
import { SessionList } from "@/components/chatops/SessionList";
import { DraftList } from "@/components/chatops/DraftList";
import type { DraftCardData } from "@/components/chatops/DraftCard";

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

export function MobileShell({
  agentPanel, onNewChat, onOpenSession, onOpenDraft, activeSessionId,
  runningTask, userName, onLogout,
}: {
  agentPanel: React.ReactNode;
  /** Session 管理 (2026-07-12) — Gemini 式抽屜 + 預設開新。 */
  onNewChat: () => void;
  onOpenSession: (sessionId: string) => void;
  /** My Drafts (2026-07-12)：點草稿 → 草稿卡插入對話（手機可 Try Run/啟用/刪，編輯卡關）。 */
  onOpenDraft: (d: DraftCardData) => void;
  activeSessionId: string | null;
  runningTask: { chat_session_id: string; goal?: string } | null;
  userName?: string | null;
  onLogout: () => void;
}) {
  const [tab, setTab] = useState<Tab>("chat");
  const [drill, setDrill] = useState<Drill>({ kind: "none" });
  const [drawerOpen, setDrawerOpen] = useState(false);
  // 新對話回饋（2026-07-12）：已在新對話時按下去畫面不變，沒回饋會以為壞了。
  const [toast, setToast] = useState("");
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 1800);
    return () => clearTimeout(t);
  }, [toast]);

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
            <button onClick={() => setDrawerOpen(true)} style={{
              width: 34, height: 34, borderRadius: "50%", border: `1px solid ${M.line}`,
              background: "#fff", color: M.ink, fontSize: 16, cursor: "pointer", flexShrink: 0,
            }}>☰</button>
            <span style={{
              width: 30, height: 30, borderRadius: 9, background: "var(--p, #1E5A44)",
              color: "#fff", display: "flex", alignItems: "center", justifyContent: "center",
              fontWeight: 800, fontSize: 14,
            }}>A</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13.5, fontWeight: 800, color: M.ink }}>AI Agent</div>
              <div style={{ fontSize: 10, color: M.ok }}>ChatOps ・ 線上</div>
            </div>
            <button onClick={() => { onNewChat(); setToast("已開新對話"); }} title="新對話" style={{
              padding: "7px 12px", borderRadius: 17, border: `1px solid ${M.line}`,
              background: "#fff", color: "var(--p, #1E5A44)", fontSize: 12.5,
              fontWeight: 700, cursor: "pointer", flexShrink: 0, whiteSpace: "nowrap",
            }}>＋ 新對話</button>
          </div>
          {/* 進行中背景工作 banner — 預設開新後回到進行中對話的入口 */}
          {runningTask && runningTask.chat_session_id !== activeSessionId && (
            <button onClick={() => onOpenSession(runningTask.chat_session_id)} style={{
              margin: "8px 12px 0", padding: "9px 13px", borderRadius: 11,
              border: "1px solid #d9c9a5", background: M.medBg, color: M.med,
              fontSize: 12.5, fontWeight: 700, textAlign: "left", cursor: "pointer",
            }}>
              有進行中的建構{runningTask.goal ? `：${runningTask.goal.slice(0, 22)}…` : ""} — 點此回到該對話
            </button>
          )}
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

        {/* 對話紀錄抽屜（Gemini 式）— 新對話 / 搜尋 / 近期 / 帳號列 */}
        {drawerOpen && (
          <div style={{ position: "absolute", inset: 0, zIndex: 20, display: "flex" }}>
            <div style={{
              width: "82%", maxWidth: 340, background: M.bg, height: "100%",
              display: "flex", flexDirection: "column",
              boxShadow: "12px 0 34px -18px rgba(20,23,60,.5)",
              padding: "14px 14px calc(10px + env(safe-area-inset-bottom, 0px))",
            }}>
              <div style={{ display: "flex", alignItems: "center", marginBottom: 10 }}>
                <span style={{ fontSize: 16, fontWeight: 800, color: M.ink }}>對話</span>
                <span style={{ flex: 1 }} />
                <button onClick={() => setDrawerOpen(false)} style={{
                  width: 30, height: 30, borderRadius: "50%", border: `1px solid ${M.line}`,
                  background: "#fff", color: M.ink, cursor: "pointer",
                }}>✕</button>
              </div>
              <button onClick={() => { setDrawerOpen(false); onNewChat(); }} style={{
                width: "100%", padding: "10px 0", borderRadius: 10, border: "none",
                background: "var(--p, #1E5A44)", color: "#fff", fontSize: 13.5,
                fontWeight: 700, cursor: "pointer", marginBottom: 10,
              }}>＋ 新對話</button>
              <div style={{ fontSize: 10.5, fontWeight: 700, color: M.faint, letterSpacing: ".05em", margin: "2px 0 6px" }}>近期</div>
              <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
                <SessionList activeId={activeSessionId}
                  onOpen={(sid) => { setDrawerOpen(false); onOpenSession(sid); }} />
              </div>
              {/* My Drafts — 點了插入草稿卡回對話（手機 Try Run/啟用可用、編輯卡關） */}
              <div style={{
                borderTop: `1px solid ${M.line}`, marginTop: 8,
                maxHeight: 200, display: "flex", flexDirection: "column",
              }}>
                <DraftList onOpenDraft={(d) => {
                  setDrawerOpen(false); setTab("chat"); onOpenDraft(d);
                }} />
              </div>
              <div style={{
                borderTop: `1px solid ${M.line}`, paddingTop: 10, marginTop: 8,
                display: "flex", alignItems: "center", gap: 9,
              }}>
                <span style={{
                  width: 30, height: 30, borderRadius: "50%", background: "var(--p, #1E5A44)",
                  color: "#fff", display: "flex", alignItems: "center", justifyContent: "center",
                  fontWeight: 800, fontSize: 13,
                }}>{(userName ?? "?").slice(0, 1).toUpperCase()}</span>
                <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: M.ink }}>{userName ?? "—"}</span>
                <button onClick={onLogout} style={{
                  border: `1px solid ${M.line}`, background: "#fff", color: M.sub,
                  fontSize: 12, fontWeight: 700, padding: "6px 12px", borderRadius: 8, cursor: "pointer",
                }}>登出</button>
              </div>
            </div>
            <div style={{ flex: 1, background: "rgba(15,18,30,.42)" }}
                 onClick={() => setDrawerOpen(false)} />
          </div>
        )}

        {/* 短暫回饋 toast */}
        {toast && (
          <div style={{
            position: "absolute", top: 64, left: "50%", transform: "translateX(-50%)",
            zIndex: 25, background: "rgba(26,29,41,.88)", color: "#fff",
            fontSize: 12.5, fontWeight: 600, padding: "7px 16px", borderRadius: 18,
          }}>{toast}</div>
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
