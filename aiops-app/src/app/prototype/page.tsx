"use client";

/**
 * UX Prototype — Chat-first vs Functional-based layout comparison
 * Visit: /prototype
 *
 * Two modes:
 *   MONITOR  — functional pages, small chat FAB
 *   INVESTIGATE — chat-left + analysis-panel-right (agent-driven)
 */

import { useState, useRef, useEffect } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

type Mode = "monitor" | "investigate";

interface ChatMsg {
  id: number;
  role: "user" | "agent";
  text: string;
  action?: "show_analysis" | "ask";
}

interface AnalysisSection {
  type: "spc" | "diagnosis" | "rootcause" | "actions";
}

// ─── Mock conversation script ─────────────────────────────────────────────────

const SCRIPT: { delay: number; msg: ChatMsg }[] = [
  { delay: 600,  msg: { id: 2, role: "agent", text: "收到，正在查詢 LOT-0007 的 SPC 資料..." } },
  { delay: 1800, msg: { id: 3, role: "agent", text: "已完成分析。STEP_038 偵測到 chamber_pressure OOC，STEP_060 呈現上漂趨勢。右側已顯示完整報告。", action: "show_analysis" } },
];

let _seq = 10;
const uid = () => ++_seq;

// ─── Palette ──────────────────────────────────────────────────────────────────

const C = {
  bg:       "#f7f8fc",
  sidebar:  "#ffffff",
  border:   "#e2e8f0",
  brand:    "#2b6cb0",
  brandBg:  "#ebf8ff",
  text:     "#1a202c",
  muted:    "#718096",
  red:      "#e53e3e",
  redBg:    "#fff5f5",
  orange:   "#dd6b20",
  green:    "#38a169",
  yellow:   "#d69e2e",
  card:     "#ffffff",
};

// ─── Tiny SPC chart (SVG) ─────────────────────────────────────────────────────

function SpcChart({ title, hasOoc, drifting }: { title: string; hasOoc?: boolean; drifting?: boolean }) {
  const W = 480; const H = 160;
  const pts = Array.from({ length: 20 }, (_, i) => {
    const drift = drifting ? i * 0.18 : 0;
    const ooc   = hasOoc && i === 14 ? 2.4 : 0;
    return 15 + drift + ooc + (Math.random() * 1.2 - 0.6);
  });
  const ucl = 17.5; const lcl = 12.5; const mid = 15;
  const toY = (v: number) => H - ((v - 10) / 10) * H;
  const xs  = pts.map((_, i) => 30 + (i / 19) * (W - 60));
  const polyline = pts.map((p, i) => `${xs[i]},${toY(p)}`).join(" ");

  return (
    <div style={{ background: "#f8fafc", borderRadius: 8, padding: "12px 16px", marginBottom: 16 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: C.muted, marginBottom: 8 }}>{title}</div>
      <svg width={W} height={H} style={{ overflow: "visible", maxWidth: "100%" }}>
        {/* UCL */}
        <line x1={30} y1={toY(ucl)} x2={W-30} y2={toY(ucl)} stroke="#fc8181" strokeDasharray="4" strokeWidth={1} />
        <text x={W-25} y={toY(ucl)+4} fontSize={9} fill="#fc8181">UCL {ucl}</text>
        {/* LCL */}
        <line x1={30} y1={toY(lcl)} x2={W-30} y2={toY(lcl)} stroke="#fc8181" strokeDasharray="4" strokeWidth={1} />
        <text x={W-25} y={toY(lcl)+4} fontSize={9} fill="#fc8181">LCL {lcl}</text>
        {/* CL */}
        <line x1={30} y1={toY(mid)} x2={W-30} y2={toY(mid)} stroke="#a0aec0" strokeDasharray="2" strokeWidth={1} />
        {/* Line */}
        <polyline points={polyline} fill="none" stroke="#3182ce" strokeWidth={1.8} />
        {/* Dots */}
        {pts.map((p, i) => {
          const ooc = p > ucl || p < lcl;
          return (
            <circle key={i} cx={xs[i]} cy={toY(p)} r={ooc ? 5 : 3}
              fill={ooc ? "#e53e3e" : drifting && i > 12 ? "#dd6b20" : "#3182ce"}
              stroke={ooc ? "#fff" : "none"} strokeWidth={1.5}
            />
          );
        })}
      </svg>
      <div style={{ display: "flex", gap: 12, marginTop: 4 }}>
        {hasOoc && <Badge color="red">⚠ OOC 已發生</Badge>}
        {drifting && <Badge color="orange">⚡ DRIFTING_UP</Badge>}
        {!hasOoc && !drifting && <Badge color="green">✓ 正常</Badge>}
        <span style={{ fontSize: 11, color: C.muted }}>UCL=17.5 LCL=12.5 | 20 批次</span>
      </div>
    </div>
  );
}

// ─── UI Atoms ─────────────────────────────────────────────────────────────────

function Badge({ color, children }: { color: "red"|"orange"|"green"|"blue"; children: React.ReactNode }) {
  const map = { red: ["#fff5f5","#c53030"], orange: ["#fffaf0","#c05621"], green: ["#f0fff4","#276749"], blue: ["#ebf8ff","#2b6cb0"] };
  const [bg, fg] = map[color];
  return (
    <span style={{ background: bg, color: fg, fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 99 }}>
      {children}
    </span>
  );
}

function Card({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{ background: C.card, borderRadius: 10, border: `1px solid ${C.border}`, padding: "16px 20px", ...style }}>
      {children}
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <div style={{ fontSize: 11, fontWeight: 700, color: C.muted, letterSpacing: "0.5px", textTransform: "uppercase", marginBottom: 12 }}>{children}</div>;
}

// ─── Monitor Mode ─────────────────────────────────────────────────────────────

function MonitorEquipRow({ id, name, status, ooc }: { id: string; name: string; status: string; ooc: number }) {
  const c = status === "RUNNING" ? C.green : status === "IDLE" ? C.yellow : C.red;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 0", borderBottom: `1px solid ${C.border}` }}>
      <div style={{ width: 8, height: 8, borderRadius: "50%", background: c, flexShrink: 0 }} />
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>{id}</div>
        <div style={{ fontSize: 11, color: C.muted }}>{name}</div>
      </div>
      <Badge color={status === "RUNNING" ? "green" : status === "IDLE" ? "orange" : "red"}>{status}</Badge>
      {ooc > 0 && <Badge color="red">{ooc} OOC</Badge>}
    </div>
  );
}

function MonitorMode({ onInvestigate }: { onInvestigate: () => void }) {
  return (
    <div style={{ display: "flex", height: "100%", overflow: "hidden" }}>
      {/* Left nav */}
      <aside style={{ width: 200, background: C.sidebar, borderRight: `1px solid ${C.border}`, padding: "16px 12px", flexShrink: 0 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: C.muted, padding: "4px 8px 10px", textTransform: "uppercase" }}>設備</div>
        {["EQP-01","EQP-02","EQP-03","EQP-04","EQP-05"].map(e => (
          <div key={e} style={{ padding: "8px 10px", borderRadius: 6, fontSize: 13, color: e === "EQP-03" ? C.brand : "#4a5568",
            background: e === "EQP-03" ? C.brandBg : "transparent", cursor: "pointer", marginBottom: 2, fontWeight: e === "EQP-03" ? 600 : 400 }}>
            {e}
          </div>
        ))}
        <div style={{ fontSize: 11, fontWeight: 700, color: C.muted, padding: "16px 8px 10px", textTransform: "uppercase" }}>批次</div>
        {["LOT-0007","LOT-0008","LOT-0009"].map(l => (
          <div key={l} style={{ padding: "8px 10px", borderRadius: 6, fontSize: 13, color: "#4a5568", cursor: "pointer", marginBottom: 2 }}>{l}</div>
        ))}
      </aside>

      {/* Main content */}
      <main style={{ flex: 1, overflowY: "auto", padding: 24, minWidth: 0 }}>
        <div style={{ marginBottom: 20 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>設備概覽</h2>
          <p style={{ fontSize: 13, color: C.muted, margin: "4px 0 0" }}>即時監控 — 5 台設備</p>
        </div>

        {/* Alert banner */}
        <div onClick={onInvestigate} style={{
          background: C.redBg, border: `1px solid #feb2b2`, borderRadius: 8,
          padding: "12px 16px", marginBottom: 20, display: "flex", alignItems: "center", gap: 12,
          cursor: "pointer",
        }}>
          <span style={{ fontSize: 18 }}>🚨</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: C.red }}>LOT-0007 @ EQP-03 — SPC OOC 警報</div>
            <div style={{ fontSize: 12, color: C.muted }}>STEP_038 chamber_pressure 超出管制界限 · 2026-03-22 10:09:53</div>
          </div>
          <span style={{ fontSize: 12, color: C.brand, fontWeight: 600 }}>點擊調查 →</span>
        </div>

        <Card>
          <SectionTitle>設備狀態</SectionTitle>
          <MonitorEquipRow id="EQP-01" name="CVD Tool 01" status="RUNNING" ooc={0} />
          <MonitorEquipRow id="EQP-02" name="CVD Tool 02" status="RUNNING" ooc={0} />
          <MonitorEquipRow id="EQP-03" name="CVD Tool 03" status="RUNNING" ooc={2} />
          <MonitorEquipRow id="EQP-04" name="Etch Tool 01" status="IDLE"    ooc={0} />
          <MonitorEquipRow id="EQP-05" name="Etch Tool 02" status="DOWN"    ooc={0} />
        </Card>
      </main>

      {/* FAB */}
      <button onClick={onInvestigate} style={{
        position: "fixed", bottom: 28, right: 28,
        width: 52, height: 52, borderRadius: "50%",
        background: C.brand, color: "#fff", border: "none",
        fontSize: 22, cursor: "pointer", boxShadow: "0 4px 14px rgba(43,108,176,0.4)",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>💬</button>
    </div>
  );
}

// ─── Investigation Mode ────────────────────────────────────────────────────────

function AnalysisPanel({ visible }: { visible: boolean }) {
  if (!visible) return (
    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: C.muted, fontSize: 13 }}>
      <div style={{ textAlign: "center" }}>
        <div style={{ fontSize: 32, marginBottom: 12 }}>🔍</div>
        <div>Agent 分析結果將顯示於此</div>
        <div style={{ fontSize: 12, marginTop: 4 }}>在左側輸入你的問題</div>
      </div>
    </div>
  );

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: 24, minWidth: 0 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>LOT-0007 SPC 分析報告</h2>
            <Badge color="red">需介入</Badge>
          </div>
          <div style={{ fontSize: 12, color: C.muted }}>EQP-03 · 2026-03-22 · 由 Agent 生成</div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button style={{ padding: "6px 14px", borderRadius: 6, border: `1px solid ${C.border}`, background: "#fff", fontSize: 12, cursor: "pointer" }}>
            📥 下載報告
          </button>
        </div>
      </div>

      {/* Summary row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 20 }}>
        {[
          { label: "SPC 狀態", value: "OOC", color: "red" as const },
          { label: "受影響站點", value: "2 站", color: "orange" as const },
          { label: "批次數", value: "18", color: "blue" as const },
          { label: "良率", value: "88%", color: "orange" as const },
        ].map(s => (
          <Card key={s.label} style={{ padding: "12px 16px" }}>
            <div style={{ fontSize: 11, color: C.muted, marginBottom: 4 }}>{s.label}</div>
            <div style={{ fontSize: 20, fontWeight: 700 }}>
              <Badge color={s.color}>{s.value}</Badge>
            </div>
          </Card>
        ))}
      </div>

      {/* SPC Charts */}
      <Card style={{ marginBottom: 16 }}>
        <SectionTitle>STEP_038 — chamber_pressure (xbar chart)</SectionTitle>
        <SpcChart title="chamber_pressure · mTorr · STEP_038 · EQP-03" hasOoc />
        <div style={{ fontSize: 12, color: "#4a5568", lineHeight: 1.6 }}>
          <strong>診斷：</strong>第 15 批次 (LOT-0001 @ 14:25:28) 量測值 <strong>19.8 mTorr</strong> 超出 UCL 17.5。
          連續 3 批次呈上漂趨勢，判定為設備漂移而非隨機異常。
        </div>
      </Card>

      <Card style={{ marginBottom: 16 }}>
        <SectionTitle>STEP_060 — chamber_pressure (xbar chart)</SectionTitle>
        <SpcChart title="chamber_pressure · mTorr · STEP_060 · EQP-03" drifting />
        <div style={{ fontSize: 12, color: "#4a5568", lineHeight: 1.6 }}>
          <strong>預警：</strong>目前未超界，但呈 DRIFTING_UP 趨勢，最高值 16.16 mTorr，
          距 UCL 僅剩 <strong>1.34 mTorr</strong>。預估 3–5 批次後可能觸發 OOC。
        </div>
      </Card>

      {/* Root Cause */}
      <Card style={{ marginBottom: 16 }}>
        <SectionTitle>根因分析</SectionTitle>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {[
            { prob: "高", icon: "🔴", text: "腔體壓力調節閥 (throttle valve) 老化 — 上次維護距今 847 小時，超出建議週期 800 小時" },
            { prob: "中", icon: "🟡", text: "製程氣體 CF4 流量在 STEP_038 有 +2.1% 偏差，可能造成壓力建立異常" },
            { prob: "低", icon: "🟢", text: "環境溫度變化 (±0.8°C)，影響有限" },
          ].map(r => (
            <div key={r.text} style={{ display: "flex", gap: 10, padding: "10px 14px", background: "#f8fafc", borderRadius: 8 }}>
              <span style={{ flexShrink: 0 }}>{r.icon}</span>
              <div>
                <span style={{ fontSize: 11, fontWeight: 700, color: C.muted, marginRight: 6 }}>[{r.prob}]</span>
                <span style={{ fontSize: 13, color: "#4a5568" }}>{r.text}</span>
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Actions */}
      <Card>
        <SectionTitle>建議行動</SectionTitle>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {[
            { icon: "✅", text: "立即安排 EQP-03 throttle valve PM（預估停機 4 小時）", urgency: "立即" },
            { icon: "✅", text: "暫緩 LOT-0008、LOT-0009 進入 STEP_038，待設備確認", urgency: "立即" },
            { icon: "✅", text: "調整 CF4 MFC 校正參數 → CF4_flow_setpoint -= 2%", urgency: "今日" },
            { icon: "✅", text: "監控 STEP_060 下 3 批次，若繼續上漂觸發二級警報", urgency: "持續" },
          ].map(a => (
            <div key={a.text} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", background: "#f0fff4", borderRadius: 8 }}>
              <span>{a.icon}</span>
              <span style={{ flex: 1, fontSize: 13, color: "#4a5568" }}>{a.text}</span>
              <Badge color={a.urgency === "立即" ? "red" : a.urgency === "今日" ? "orange" : "blue"}>{a.urgency}</Badge>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function InvestigateMode({ onBack }: { onBack: () => void }) {
  const [msgs, setMsgs] = useState<ChatMsg[]>([
    { id: 1, role: "user", text: "查一下 LOT-0007 的 SPC 狀況" },
  ]);
  const [input, setInput]       = useState("");
  const [showAnalysis, setShowAnalysis] = useState(false);
  const [typing, setTyping]     = useState(false);
  const [scriptIdx, setScriptIdx] = useState(0);
  const chatRef = useRef<HTMLDivElement>(null);

  // Auto-play script
  useEffect(() => {
    if (scriptIdx >= SCRIPT.length) return;
    const { delay, msg } = SCRIPT[scriptIdx];
    setTyping(true);
    const t = setTimeout(() => {
      setTyping(false);
      setMsgs(prev => [...prev, msg]);
      if (msg.action === "show_analysis") setShowAnalysis(true);
      setScriptIdx(i => i + 1);
    }, delay);
    return () => clearTimeout(t);
  }, [scriptIdx]);

  useEffect(() => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: "smooth" });
  }, [msgs, typing]);

  function handleSend() {
    if (!input.trim()) return;
    setMsgs(prev => [...prev, { id: uid(), role: "user", text: input }]);
    setInput("");
    // Mock simple reply
    setTimeout(() => {
      setMsgs(prev => [...prev, { id: uid(), role: "agent", text: "已收到，我來查一下。" }]);
    }, 800);
  }

  return (
    <div style={{ display: "flex", height: "100%", overflow: "hidden" }}>

      {/* ── Chat panel (left, narrow) ─────────────────── */}
      <div style={{
        width: 300, flexShrink: 0,
        display: "flex", flexDirection: "column",
        borderRight: `1px solid ${C.border}`,
        background: C.sidebar,
      }}>
        {/* Chat header */}
        <div style={{ padding: "12px 16px", borderBottom: `1px solid ${C.border}`, display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ width: 8, height: 8, borderRadius: "50%", background: C.green }} />
          <span style={{ fontSize: 13, fontWeight: 600 }}>AI Agent</span>
          <span style={{ fontSize: 11, color: C.muted, marginLeft: "auto" }}>調查中</span>
        </div>

        {/* Messages */}
        <div ref={chatRef} style={{ flex: 1, overflowY: "auto", padding: 14, display: "flex", flexDirection: "column", gap: 10 }}>
          {msgs.map(m => (
            <div key={m.id} style={{ display: "flex", flexDirection: "column", alignItems: m.role === "user" ? "flex-end" : "flex-start" }}>
              <div style={{
                maxWidth: "88%", padding: "8px 12px", borderRadius: m.role === "user" ? "12px 12px 3px 12px" : "12px 12px 12px 3px",
                background: m.role === "user" ? C.brand : "#f1f5f9",
                color: m.role === "user" ? "#fff" : C.text,
                fontSize: 13, lineHeight: 1.5,
              }}>
                {m.text}
              </div>
              {m.action === "show_analysis" && (
                <div style={{ fontSize: 11, color: C.brand, marginTop: 4, cursor: "pointer" }}>
                  📊 右側查看完整報告 →
                </div>
              )}
            </div>
          ))}
          {typing && (
            <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "8px 12px" }}>
              {[0,1,2].map(i => (
                <div key={i} style={{
                  width: 6, height: 6, borderRadius: "50%", background: C.muted,
                  animation: "pulse 1.2s ease-in-out infinite",
                  animationDelay: `${i * 0.2}s`,
                }} />
              ))}
            </div>
          )}
        </div>

        {/* Input */}
        <div style={{ padding: 12, borderTop: `1px solid ${C.border}` }}>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleSend()}
              placeholder="輸入指令..."
              style={{
                flex: 1, padding: "8px 12px", borderRadius: 8,
                border: `1px solid ${C.border}`, fontSize: 13,
                outline: "none", background: "#fff",
              }}
            />
            <button onClick={handleSend} style={{
              padding: "8px 14px", borderRadius: 8,
              background: C.brand, color: "#fff",
              border: "none", fontSize: 13, cursor: "pointer",
            }}>送</button>
          </div>
          <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
            {["查前後站", "顯示趨勢圖", "建議 PM 時間"].map(s => (
              <button key={s} onClick={() => setInput(s)} style={{
                padding: "3px 8px", borderRadius: 99, fontSize: 11,
                border: `1px solid ${C.border}`, background: "#fff",
                color: C.muted, cursor: "pointer",
              }}>{s}</button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Analysis Panel (right, main) ─────────────── */}
      <AnalysisPanel visible={showAnalysis} />
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function PrototypePage() {
  const [mode, setMode] = useState<Mode>("monitor");

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: C.bg, fontFamily: "system-ui, sans-serif", color: C.text }}>

      {/* Topbar */}
      <header style={{
        height: 48, background: "#fff", borderBottom: `1px solid ${C.border}`,
        display: "flex", alignItems: "center", padding: "0 20px", gap: 16, flexShrink: 0,
      }}>
        <span style={{ fontWeight: 700, fontSize: 15, color: C.brand }}>AIOps</span>
        <span style={{ fontSize: 11, color: C.muted, background: "#f7f8fc", border: `1px solid ${C.border}`, padding: "1px 8px", borderRadius: 8 }}>PROTOTYPE</span>

        <div style={{ display: "flex", gap: 0, marginLeft: 16, background: "#f1f5f9", borderRadius: 8, padding: 3 }}>
          {(["monitor", "investigate"] as Mode[]).map(m => (
            <button key={m} onClick={() => setMode(m)} style={{
              padding: "5px 14px", borderRadius: 6, border: "none", fontSize: 12, fontWeight: 600,
              cursor: "pointer",
              background: mode === m ? "#fff" : "transparent",
              color: mode === m ? C.brand : C.muted,
              boxShadow: mode === m ? "0 1px 3px rgba(0,0,0,0.1)" : "none",
            }}>
              {m === "monitor" ? "📊 監控模式" : "🔍 調查模式"}
            </button>
          ))}
        </div>

        <div style={{ marginLeft: "auto", fontSize: 12, color: C.muted }}>
          {mode === "monitor"
            ? "點擊警報橫幅或 💬 按鈕切換調查模式"
            : "Chat 保持簡潔，分析結果顯示於右側"}
        </div>
      </header>

      {/* Content */}
      <div style={{ flex: 1, overflow: "hidden" }}>
        {mode === "monitor"
          ? <MonitorMode onInvestigate={() => setMode("investigate")} />
          : <InvestigateMode onBack={() => setMode("monitor")} />
        }
      </div>

      <style>{`
        @keyframes pulse {
          0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
          40% { opacity: 1; transform: scale(1); }
        }
      `}</style>
    </div>
  );
}
