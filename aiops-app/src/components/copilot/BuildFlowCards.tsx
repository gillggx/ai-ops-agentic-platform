/**
 * BuildFlowCards — 對話分頁重整（AGENT_CHAT_ONLY spec, 2026-07-05）。
 *
 * 一次 build 對話 = 4 個訊息塊：user 泡 / INTENT 卡 / BUILD PLAN 卡（原地
 * 變身：草案 → 建構中 → 完成）/ 完成卡。硬規則：
 *   - 一張卡一個生命週期（同 message id 原地更新，不貼新卡）
 *   - 目標句只出現一次（plan 卡）
 *   - 任何選擇一經點選即鎖定停用
 *   - 內部 tag（[intent_confirmed:…]）不進訊息流
 *
 * 語彙 tokens 與 AgentConsole 共用（§6）。禁 emoji — 幾何符號 ✓ ✕ ▲ ◆ ○ ● ▣。
 */
"use client";

import * as React from "react";
import { useTranslations } from "next-intl";
import type { GoalPhase, PlanRemoval } from "@/components/pipeline-builder/v30/GoalPlanCard";
import type { IntentBullet } from "@/components/chat/BulletConfirmCard";

// ── 語彙 tokens（§6）─────────────────────────────────────────────────
export const CHAT_T = {
  panelBg: "#fbfbf9", card: "#fff", lockedCard: "#fdfdfc",
  line: "#e9e7e2", innerLine: "#efede8",
  ink: "#211f1c", sub: "#55534d", weak: "#8a877e", faint: "#a09d95",
  bubble: "#efede8", chipBorder: "#dcdad4",
  amber: "#b45309", amberDeep: "#8a5a06", amberBg: "#fdfaf2", amberBorder: "#efe1bd", amberChip: "#f3e7c9",
  green: "#047857", greenBg: "#eafaf3", greenMark: "#059669",
  purple: "#6d28d9", purpleAlt: "#7c3aed",
  plannerBlue: "#2563eb",
  repair: "#d97706", repairBg: "#fdf5e7", repairText: "#a5680a",
  mono: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
} as const;

const headStyle: React.CSSProperties = {
  fontSize: 9.5, fontWeight: 700, letterSpacing: "0.08em",
  color: CHAT_T.weak, fontFamily: CHAT_T.mono,
};

function chipS(bg: string, c: string, br?: string): React.CSSProperties {
  return {
    display: "inline-block", padding: "1px 7px", borderRadius: 4,
    fontSize: 9.5, fontFamily: CHAT_T.mono, fontWeight: 600,
    background: bg, color: c, border: `1px solid ${br ?? "transparent"}`,
    whiteSpace: "nowrap", flex: "none",
  };
}

function cardStyle(locked: boolean): React.CSSProperties {
  return {
    border: `1px solid ${CHAT_T.line}`, borderRadius: 9,
    background: locked ? CHAT_T.lockedCard : CHAT_T.card,
    padding: "11px 12px", width: "100%", boxSizing: "border-box",
  };
}

const DISABLED: React.CSSProperties = { opacity: 0.45, cursor: "default", pointerEvents: "none" };

function nowHM(): string {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

// ── User 泡內容：context tag → chip（§3.1）──────────────────────────
/** 內部 tag（[intent_confirmed:…] / [intent=…]）從顯示中剝除；短 context
 *  tag（[EQP-01] 等，無空白 ≤ 24 字）渲染為 chip；其餘照原文。 */
export function renderUserContent(text: string): React.ReactNode {
  const cleaned = text.replace(/^\s*\[(intent_confirmed:|intent=)[^\]]*\]\s*/, "");
  const parts = cleaned.split(/(\[[^\]\s]{1,24}\])/g);
  return parts.map((p, i) => {
    const m = /^\[([^\]\s]{1,24})\]$/.exec(p);
    if (m) {
      return (
        <span key={i} style={{
          display: "inline-block", padding: "0 5px", margin: "0 2px",
          background: "#fff", border: `1px solid ${CHAT_T.chipBorder}`,
          color: CHAT_T.sub, fontFamily: CHAT_T.mono, fontSize: 10,
          borderRadius: 4, verticalAlign: "baseline",
        }}>{m[1]}</span>
      );
    }
    return <span key={i} style={{ whiteSpace: "pre-wrap" }}>{p}</span>;
  });
}

// Design v2 (2026-07-10): user bubble is the theme primary — dark pill with
// white text, per the ChatOps/Copilot handoff mockups.
export const userBubbleStyle: React.CSSProperties = {
  alignSelf: "flex-end", maxWidth: "85%",
  background: "var(--p, #1E5A44)", color: "#ffffff",
  fontSize: 11.5, lineHeight: 1.7, padding: "8px 12px",
  borderRadius: "10px 10px 3px 10px",
};

// ── ① INTENT 卡（§3.2 / §4）────────────────────────────────────────
export type IntentAction = "ok" | "reject" | "edit";
export type IntentResolved = "confirmed" | "refused" | "error";

export function IntentCard({
  bullets, tooVagueReason, resolved, collapsed, busy, onSubmit,
}: {
  bullets: IntentBullet[];
  tooVagueReason?: string;
  resolved?: IntentResolved;
  /** 建構開始後收斂為單行摘要（§4 第三列）。 */
  collapsed?: boolean;
  busy?: boolean;
  onSubmit: (
    confirmations: Record<string, { action: IntentAction; edit_text?: string }>,
  ) => void;
}) {
  const t = useTranslations("buildFlow.intent");
  const [picked, setPicked] = React.useState<Record<string, string>>({});
  const [edits, setEdits] = React.useState<Record<string, string>>({});
  const [editing, setEditing] = React.useState<Record<string, boolean>>({});
  const [confirmedAt, setConfirmedAt] = React.useState<string>("");
  // 點選即鎖定（§4）— onSubmit 是 async，resolved 由 parent 事後設定；
  // submitted 讓卡片在送出瞬間就停用，防雙擊。
  const [submitted, setSubmitted] = React.useState(false);

  const optionBullets = bullets.filter((b) => (b.options ?? []).length > 0);
  const locked = resolved !== undefined || !!busy || submitted;

  const buildConfirmations = (
    pickedNow: Record<string, string>,
  ): Record<string, { action: IntentAction; edit_text?: string }> => {
    const out: Record<string, { action: IntentAction; edit_text?: string }> = {};
    for (const b of bullets) {
      const opt = pickedNow[b.id];
      const editText = edits[b.id]?.trim();
      if (opt) out[b.id] = { action: "edit", edit_text: opt };
      else if (editText) out[b.id] = { action: "edit", edit_text: editText };
      else out[b.id] = { action: "ok" };
    }
    return out;
  };

  const pickOption = (bulletId: string, value: string) => {
    if (locked) return;
    const next = { ...picked, [bulletId]: value };
    setPicked(next);
    // 點選任一選項即送出並鎖定 — 所有提問都有答案時立刻送出
    const allAnswered = optionBullets.every((b) => next[b.id]);
    if (allAnswered) {
      setConfirmedAt(nowHM());
      setSubmitted(true);
      onSubmit(buildConfirmations(next));
    }
  };

  const submitPlain = () => {
    if (locked) return;
    setConfirmedAt(nowHM());
    setSubmitted(true);
    onSubmit(buildConfirmations(picked));
  };

  const cancel = () => {
    if (locked) return;
    setSubmitted(true);
    const out: Record<string, { action: IntentAction }> = {};
    for (const b of bullets) out[b.id] = { action: "reject" };
    onSubmit(out);
  };

  // 收斂單行（建構開始後）
  if (collapsed && resolved === "confirmed") {
    const answers = Object.values(picked).join("＋") || bullets[0]?.text?.slice(0, 40) || "";
    return (
      <div style={{
        ...cardStyle(true), padding: "7px 12px",
        display: "flex", alignItems: "baseline", gap: 8,
      }}>
        <span style={headStyle}>INTENT</span>
        <span style={{ fontSize: 10.5, color: CHAT_T.sub, flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          <span style={{ color: CHAT_T.greenMark }}>✓ </span>{answers}
        </span>
        <span style={{ fontSize: 9.5, color: CHAT_T.faint, fontFamily: CHAT_T.mono, flex: "none" }}>{t("locked")}</span>
      </div>
    );
  }

  const answered = resolved === "confirmed";
  const refusedOrErr = resolved === "refused" || resolved === "error";

  return (
    <div style={cardStyle(locked)}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <span style={{ ...headStyle, color: locked ? CHAT_T.faint : CHAT_T.weak }}>
          {answered ? t("headerConfirmed", { time: confirmedAt || "" }) : refusedOrErr ? t("headerCancelled") : t("headerPending")}
        </span>
        {!resolved && !busy && !submitted && (
          <span style={chipS(CHAT_T.amberBg, CHAT_T.amberDeep, CHAT_T.amberBorder)}>{t("chipPending")}</span>
        )}
        {(busy || submitted) && !resolved && <span style={chipS(CHAT_T.ink, "#fff")}>{t("chipSending")}</span>}
        {answered && <span style={chipS(CHAT_T.greenBg, CHAT_T.green)}>{t("chipLocked")}</span>}
        {refusedOrErr && <span style={chipS("#f1efe9", CHAT_T.weak)}>{t("chipCancelled")}</span>}
      </div>

      {tooVagueReason && !resolved && (
        <div style={{
          marginTop: 8, fontSize: 10.5, color: CHAT_T.amberDeep,
          padding: "6px 8px", background: CHAT_T.amberBg,
          border: `1px solid ${CHAT_T.amberBorder}`, borderRadius: 7,
        }}>
          {t("tooVague", { reason: tooVagueReason.slice(0, 200) })}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 7, marginTop: 8 }}>
        {bullets.map((b) => {
          const opts = b.options ?? [];
          if (opts.length > 0) {
            return (
              <div key={b.id} style={{
                background: CHAT_T.amberBg, border: `1px solid ${CHAT_T.amberBorder}`,
                borderRadius: 7, padding: "8px 10px",
              }}>
                <div style={{ display: "flex", gap: 7, alignItems: "baseline" }}>
                  <span style={{ color: CHAT_T.amber, fontWeight: 700, fontSize: 11, flex: "none" }}>?</span>
                  <span style={{ fontSize: 11, fontWeight: 600, color: "#7c4a03", lineHeight: 1.55 }}>{b.text}</span>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 7 }}>
                  {opts.map((o) => {
                    const sel = picked[b.id] === o.value;
                    const dimOther = locked && !sel;
                    return (
                      <div
                        key={o.value}
                        onClick={() => pickOption(b.id, o.value)}
                        style={{
                          display: "flex", alignItems: "center", gap: 8,
                          fontSize: 11, color: CHAT_T.ink, cursor: locked ? "default" : "pointer",
                          padding: "2px 0",
                          ...(dimOther ? DISABLED : {}),
                        }}
                      >
                        <span style={{
                          width: 11, height: 11, borderRadius: "50%", flex: "none",
                          border: `1.5px solid ${sel ? CHAT_T.ink : "#c9c6bf"}`,
                          background: sel ? CHAT_T.ink : "#fff",
                          boxSizing: "border-box",
                        }} />
                        <span style={{ fontWeight: sel ? 700 : 400, flex: 1 }}>{o.label}</span>
                        {sel && locked && <span style={{ color: CHAT_T.greenMark, fontSize: 11 }}>✓</span>}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          }
          // 無選項的 bullet — 一行敘述，可點擊改寫
          return (
            <div key={b.id} style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
              <span style={{ fontSize: 9.5, color: CHAT_T.faint, fontFamily: CHAT_T.mono, flex: "none" }}>▸</span>
              {editing[b.id] && !locked ? (
                <input
                  autoFocus
                  value={edits[b.id] ?? b.text}
                  onChange={(e) => setEdits((p) => ({ ...p, [b.id]: e.target.value }))}
                  onBlur={() => setEditing((p) => ({ ...p, [b.id]: false }))}
                  onKeyDown={(e) => { if (e.key === "Enter") setEditing((p) => ({ ...p, [b.id]: false })); }}
                  style={{
                    flex: 1, fontSize: 11, padding: "2px 6px",
                    border: `1px solid ${CHAT_T.chipBorder}`, borderRadius: 4,
                    fontFamily: "inherit", color: CHAT_T.ink, background: "#fff",
                  }}
                />
              ) : (
                <span
                  onClick={() => { if (!locked) setEditing((p) => ({ ...p, [b.id]: true })); }}
                  style={{ fontSize: 11, lineHeight: 1.55, color: CHAT_T.ink, cursor: locked ? "default" : "text", flex: 1 }}
                  title={locked ? undefined : t("clickToEdit")}
                >
                  {edits[b.id]?.trim() ? edits[b.id] : b.text}
                  {edits[b.id]?.trim() && (
                    <span style={{ fontSize: 9.5, color: CHAT_T.purple, fontFamily: CHAT_T.mono }}> · {t("edited")}</span>
                  )}
                </span>
              )}
            </div>
          );
        })}
      </div>

      {!resolved && (
        <div style={{
          display: "flex", justifyContent: "space-between", alignItems: "center",
          marginTop: 10, paddingTop: 8, borderTop: `1px solid ${CHAT_T.innerLine}`,
          ...(busy ? DISABLED : {}),
        }}>
          <span style={{ fontSize: 10, color: CHAT_T.faint }}>
            {optionBullets.length > 0 ? t("hintOptions") : t("hintPlain")}
          </span>
          <div style={{ display: "flex", gap: 6 }}>
            <button onClick={cancel} style={{
              border: `1px solid ${CHAT_T.chipBorder}`, background: "#fff", color: CHAT_T.sub,
              fontSize: 11, padding: "4px 12px", borderRadius: 7, cursor: "pointer", fontFamily: "inherit",
            }}>{t("cancel")}</button>
            {optionBullets.length === 0 && (
              <button onClick={submitPlain} style={{
                border: `1px solid ${CHAT_T.ink}`, background: CHAT_T.ink, color: "#fff",
                fontSize: 11, fontWeight: 600, padding: "4px 14px", borderRadius: 7,
                cursor: "pointer", fontFamily: "inherit",
              }}>{t("confirmStart")}</button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── ②③ BUILD PLAN 卡（§3.3 / §3.4 / §5）────────────────────────────
export interface PhaseRuntimeUI {
  status: "pending" | "in_progress" | "completed" | "failed";
  rejects?: number;
  rounds?: number;
  repair?: boolean;
  /** mono meta：last: add_node → n3 */
  lastOp?: string;
  /** 完成 phase 的結果行：▣ block_x → 100 rows */
  result?: string;
  /** 失敗 / 反思原因 */
  note?: string;
}

export type BuildPlanStatus = "draft" | "building" | "done" | "cancelled" | "error";

export interface BuildPlanState {
  sessionId: string;
  buildSessionId?: string;
  summary?: string;
  phases: GoalPhase[];
  removals?: PlanRemoval[];
  status: BuildPlanStatus;
  confirmedAt?: string;
  /** user 編輯過的 phase id（W1 訊號） */
  editedIds?: string[];
  runtime: Record<string, PhaseRuntimeUI>;
  errorReason?: string;
}

const EXPECTED_KEYS = new Set(
  ["raw_data", "transform", "chart", "table", "scalar", "verdict", "alarm"],
);

export function BuildPlanCard({
  state, busy, onConfirm, onCancel, onConsoleLink,
}: {
  state: BuildPlanState;
  busy?: boolean;
  onConfirm: (phases: GoalPhase[], removals?: PlanRemoval[]) => void;
  onCancel: () => void;
  onConsoleLink?: () => void;
}) {
  const { phases, runtime, status } = state;
  const t = useTranslations("buildFlow.plan");
  const te = useTranslations("buildFlow.expected");
  const [edits, setEdits] = React.useState<Record<string, string>>({});
  const [editing, setEditing] = React.useState<string | null>(null);
  const draft = status === "draft" && !busy;

  const effectivePhases = (): GoalPhase[] =>
    phases.map((p) => (edits[p.id]?.trim() ? { ...p, goal: edits[p.id].trim() } : p));

  const editedIds = status === "draft"
    ? Object.keys(edits).filter((id) => edits[id]?.trim() && edits[id].trim() !== phases.find((p) => p.id === id)?.goal)
    : (state.editedIds ?? []);

  const doneCount = phases.filter((p) => runtime[p.id]?.status === "completed").length;
  const total = phases.length;

  const headline =
    status === "draft" ? `BUILD PLAN · ${total} PHASES` : `BUILD PLAN · ${doneCount}/${total} DONE`;

  const chip =
    status === "draft" ? <span style={chipS("#f1efe9", CHAT_T.weak)}>{t("chipDraft")}</span>
    : status === "building" ? <span style={chipS(CHAT_T.ink, "#fff")}>{t("chipBuilding")}</span>
    : status === "done" ? <span style={chipS(CHAT_T.greenBg, CHAT_T.green)}>{t("chipDone")}</span>
    : status === "cancelled" ? <span style={chipS("#f1efe9", CHAT_T.weak)}>{t("chipCancelled")}</span>
    : <span style={chipS(CHAT_T.amberChip, CHAT_T.amberDeep)}>{t("chipAborted")}</span>;

  const locked = status !== "draft";

  return (
    <div style={cardStyle(locked && status !== "building")}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <span style={headStyle}>{headline}</span>
        {chip}
      </div>

      {/* 目標句 — 全對話唯一一次 */}
      {state.summary && (
        <div style={{ fontSize: 11.5, fontWeight: 600, color: CHAT_T.ink, lineHeight: 1.55, marginTop: 7 }}>
          {state.summary}
        </div>
      )}
      {locked && state.confirmedAt && (
        <div style={{ fontSize: 10, color: CHAT_T.faint, marginTop: 3 }}>
          <span style={{ color: CHAT_T.greenMark }}>✓</span> {t("confirmedLine", { time: state.confirmedAt })}
        </div>
      )}
      {status === "error" && state.errorReason && (
        <div style={{
          marginTop: 7, fontSize: 10.5, color: CHAT_T.amberDeep,
          padding: "5px 8px", background: CHAT_T.amberBg,
          border: `1px solid ${CHAT_T.amberBorder}`, borderRadius: 7,
        }}>
          ▲ {state.errorReason.slice(0, 180)}
        </div>
      )}

      {/* phase 列 */}
      <div style={{ display: "flex", flexDirection: "column", gap: 7, marginTop: 9 }}>
        {phases.map((p) => {
          const rt = runtime[p.id];
          const st = rt?.status ?? "pending";
          const glyph = locked
            ? (st === "completed" ? "✓" : st === "failed" ? "✕" : st === "in_progress" ? "●" : "○")
            : null;
          const glyphColor =
            st === "completed" ? (rt?.repair ? CHAT_T.repair : CHAT_T.greenMark)
            : st === "failed" ? CHAT_T.amber
            : st === "in_progress" ? CHAT_T.ink : CHAT_T.faint;
          const chips: React.ReactNode[] = [];
          if (locked) {
            if (st === "completed") {
              chips.push(rt?.repair
                ? <span key="s" style={chipS(CHAT_T.repairBg, CHAT_T.repairText, "#f0dcb4")}>{t("phaseRepaired")}</span>
                : <span key="s" style={chipS(CHAT_T.greenBg, CHAT_T.green)}>{t("phaseDone")}</span>);
            } else if (st === "in_progress") {
              chips.push(<span key="s" style={chipS(CHAT_T.ink, "#fff")}>{t("phaseInProgress")}</span>);
            } else if (st === "failed") {
              chips.push(<span key="s" style={chipS(CHAT_T.amberChip, CHAT_T.amberDeep)}>{t("phaseFailed")}</span>);
            }
            if (rt?.rejects) {
              chips.push(<span key="r" style={chipS(CHAT_T.amberChip, CHAT_T.amberDeep)}>{t("phaseRejected", { n: rt.rejects })}</span>);
            }
          }
          const meta: string[] = [];
          if (locked && rt?.rounds) meta.push(`r${rt.rounds}/32`);
          if (locked && rt?.lastOp) meta.push(`last: ${rt.lastOp}`);
          const edited = editedIds.includes(p.id);
          return (
            <div key={p.id} style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
              {glyph ? (
                <span style={{ color: glyphColor, flex: "none", fontSize: 11, width: 13, textAlign: "center" }}>{glyph}</span>
              ) : (
                <span style={{
                  flex: "none", fontSize: 9.5, fontWeight: 700,
                  color: CHAT_T.plannerBlue, fontFamily: CHAT_T.mono, width: 16,
                }}>{p.id}</span>
              )}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", gap: 6, alignItems: "baseline", flexWrap: "wrap" }}>
                  {draft && editing === p.id ? (
                    <input
                      autoFocus
                      value={edits[p.id] ?? p.goal}
                      onChange={(e) => setEdits((prev) => ({ ...prev, [p.id]: e.target.value }))}
                      onBlur={() => setEditing(null)}
                      onKeyDown={(e) => { if (e.key === "Enter") setEditing(null); }}
                      style={{
                        flex: 1, minWidth: 160, fontSize: 11, padding: "2px 6px",
                        border: `1px solid ${CHAT_T.chipBorder}`, borderRadius: 4,
                        fontFamily: "inherit", color: CHAT_T.ink, background: "#fff",
                      }}
                    />
                  ) : (
                    <span
                      onClick={() => { if (draft) setEditing(p.id); }}
                      style={{ fontSize: 11, lineHeight: 1.5, color: CHAT_T.ink, cursor: draft ? "text" : "default" }}
                    >
                      {edits[p.id]?.trim() && status === "draft" ? edits[p.id] : p.goal}
                    </span>
                  )}
                  <span style={chipS("#f1efe9", CHAT_T.weak)}>{EXPECTED_KEYS.has(p.expected) ? te(p.expected) : p.expected}</span>
                  {chips}
                  {meta.length > 0 && (
                    <span style={{ fontFamily: CHAT_T.mono, fontSize: 9, color: CHAT_T.faint }}>{meta.join(" · ")}</span>
                  )}
                </div>
                {edited && (
                  <div style={{ fontSize: 10, color: CHAT_T.purple, lineHeight: 1.5 }}>
                    ◆ {t("editedW1")}
                  </div>
                )}
                {locked && st === "completed" && rt?.result && (
                  <div style={{ fontSize: 10, color: CHAT_T.green, marginTop: 2 }}>▣ {rt.result}</div>
                )}
                {locked && rt?.note && st !== "completed" && (
                  <div style={{ fontSize: 10, color: CHAT_T.amberDeep, marginTop: 2 }}>{rt.note}</div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* 草案：按鈕列 + 底註。確認後按鈕「移除」（§4）。 */}
      {status === "draft" && (
        <>
          <div style={{ display: "flex", gap: 8, marginTop: 11, ...(busy ? DISABLED : {}) }}>
            <button onClick={onCancel} style={{
              border: `1px solid ${CHAT_T.chipBorder}`, background: "#fff", color: CHAT_T.sub,
              fontSize: 11, padding: "6px 14px", borderRadius: 7, cursor: "pointer", fontFamily: "inherit",
            }}>{t("cancel")}</button>
            <button
              onClick={() => onConfirm(effectivePhases(), state.removals)}
              style={{
                flex: 1, border: `1px solid ${CHAT_T.ink}`, background: CHAT_T.ink, color: "#fff",
                fontSize: 11, fontWeight: 600, padding: "6px 14px", borderRadius: 7,
                cursor: "pointer", fontFamily: "inherit",
              }}
            >{busy ? t("sending") : t("confirmStart")}</button>
          </div>
          <div style={{ fontSize: 10, color: CHAT_T.faint, marginTop: 7 }}>
            {t("footnotePre")}{" "}
            <span style={{ color: CHAT_T.purple, fontFamily: CHAT_T.mono }}>W1</span>{" "}
            {t("footnotePost")}
          </div>
        </>
      )}

      {/* 建構中 / 完成：卡底 Console 連結 */}
      {locked && status !== "cancelled" && onConsoleLink && (
        <div style={{
          marginTop: 9, paddingTop: 8, borderTop: `1px solid ${CHAT_T.innerLine}`,
          fontSize: 10, color: CHAT_T.weak,
        }}>
          {t("consoleLinkPre")}{" "}
          <span onClick={onConsoleLink} style={{ color: CHAT_T.ink, fontWeight: 600, cursor: "pointer", textDecoration: "underline" }}>
            {t("consoleLinkLabel")}
          </span>
        </div>
      )}
    </div>
  );
}

// ── 完成卡（§3.5）────────────────────────────────────────────────────
export interface BuildDoneState {
  text: string;                       // ✓ 建構完成 — 3 nodes / 2 edges，…
  verified?: string;                  // ▣ 數值已驗證（…）
  learned: string[];                  // ["W1 偏好（…）"]
  rating?: 1 | -1 | null;
}

export function BuildDoneCard({
  state, onRate,
}: {
  state: BuildDoneState;
  onRate?: (rating: 1 | -1) => void;
}) {
  const t = useTranslations("buildFlow.done");
  const rated = state.rating != null;
  return (
    <div style={{ ...cardStyle(false), padding: "9px 12px" }}>
      <div style={{ fontSize: 11, lineHeight: 1.6, color: CHAT_T.sub }}>
        <span style={{ color: CHAT_T.greenMark }}>✓</span> {state.text}
      </div>
      {state.verified && (
        <div style={{ fontSize: 10, color: CHAT_T.green, marginTop: 3 }}>▣ {state.verified}</div>
      )}
      {state.learned.length > 0 && (
        <div style={{ fontSize: 10, color: CHAT_T.purple, marginTop: 3 }}>
          ◆ {t("learned", { n: state.learned.length })}{state.learned.join(" · ")}
        </div>
      )}
      {onRate && (
        <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
          {([[t("helpful"), 1], [t("inaccurate"), -1]] as const).map(([label, val]) => {
            const active = state.rating === val;
            return (
              <button
                key={label}
                onClick={() => { if (!rated) onRate(val); }}
                style={{
                  border: `1px solid ${active ? CHAT_T.ink : CHAT_T.chipBorder}`,
                  background: active ? CHAT_T.ink : "#fff",
                  color: active ? "#fff" : CHAT_T.sub,
                  fontSize: 10.5, padding: "3px 12px", borderRadius: 7,
                  cursor: rated ? "default" : "pointer", fontFamily: "inherit",
                  ...(rated && !active ? DISABLED : {}),
                }}
              >{label}</button>
            );
          })}
        </div>
      )}
    </div>
  );
}
