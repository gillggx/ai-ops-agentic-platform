"use client";

/**
 * v1.7 Slash Command Menu.
 *
 * Replaces the 3 example-prompt pills + 3 intent chips above the chat
 * composer with a tighter, IDE-style slash menu: type "/" at the start
 * of the textarea and a floating list pops up with categorised
 * commands. ↑/↓/Enter/Esc work; mouse hover/click also works.
 *
 * Curated by category (SPC / APC / 巡檢 / 診斷). Each command has a
 * Chinese template the user fills in — the menu picks the template
 * and the user can edit before sending.
 */

import { useEffect, useMemo, useRef, useState } from "react";

export interface SlashCommand {
  cat: "spc" | "apc" | "patrol" | "diag";
  ico: string;
  key: string;
  title: string;
  desc: string;
  tpl: string;
}

// "diag" category dropped 2026-05-22 — all 3 diag commands removed (alarm
// MCP unavailable / time-window-around-anchor unsupported). Keep type alias
// for back-compat but UI no longer renders that group.
export const SLASH_CATEGORIES: Array<{ key: SlashCommand["cat"]; label: string }> = [
  { key: "spc",    label: "📊 SPC" },
  { key: "apc",    label: "🔧 APC" },
  { key: "patrol", label: "📋 巡檢" },
];

// 2026-05-22 — Audit-validated list. Each command was smoke-tested against
// /internal/agent/build + plan-confirm and produced a non-error build with
// at least one chart block. See docs/slash-command-audit-2026-05-21-after-v50.md.
//
// Failing commands removed: apc-corr / apc-recipe / patrol-alarms /
// patrol-recipe-consist / diag-alarm / diag-ooc-point / diag-walkback.
// (Alarm-related fails won't be re-introduced until get_alarms MCP exists.)
export const SLASH_COMMANDS: SlashCommand[] = [
  // ── SPC (retained from previous audit — all OK) ─────────────────────
  { cat: "spc", ico: "📈", key: "spc-trend",
    title: "看某機台某站的 xbar 趨勢",
    desc: "拉最近 N 筆 SPC 資料畫 xbar 控制圖（含 UCL/LCL）",
    tpl: "幫我看 [EQP-01] [STEP_001] 最近 100 筆 xbar 趨勢" },
  { cat: "spc", ico: "🔍", key: "spc-ooc",
    title: "找最近 OOC 集中的機台",
    desc: "彙總過去 24h 各機台 OOC 次數，找出異常熱點",
    tpl: "過去 24 小時哪些機台 SPC OOC 最多？列前 5 名" },
  { cat: "spc", ico: "📊", key: "spc-cpk",
    title: "比較 R / Cpk / Cpk_std",
    desc: "三條線並列，看製程能力是否退化",
    tpl: "比較 [EQP-01] [STEP_001] 過去 7 天的 R、Cpk、Cpk_std 趨勢" },
  { cat: "spc", ico: "📦", key: "spc-multi-tool",
    title: "多機台同站點 xbar 疊圖比較",
    desc: "同一張 chart 上以不同顏色顯示多台機台的 xbar 趨勢線（color=toolID）",
    tpl: "比較 [EQP-01,EQP-02,EQP-03,EQP-04,EQP-05] 在 [STEP_001] 的 xbar 趨勢，畫成一張彩色 line chart（color=toolID）" },
  { cat: "spc", ico: "📉", key: "spc-drift",
    title: "Drift 偵測 + 分佈診斷三件組",
    desc: "EWMA-CUSUM 抓小幅漂移 + Box plot 看 lot 變異 + Q-Q 檢定常態性",
    tpl: "過去 7 天 [EQP-01] [STEP_001] 的 spc_xbar_chart_value：(1) block_ewma_cusum (mode='cusum', k=0.5, h=4) 偵測 < 1σ 小幅 drift；(2) block_box_plot 比較各 lot 之間的分佈差異；(3) block_probability_plot 檢定是否符合常態（給 Cpk 計算打底）" },

  // ── SPC (new, audit 2026-05-22 — all built OK) ──────────────────────
  { cat: "spc", ico: "📊", key: "spc-xbar-r-pair",
    title: "X̄/R 對偶管制圖",
    desc: "X̄ + R 兩張圖並列，WECO 規則 highlight",
    tpl: "EQP-01 STEP_001 最近 7 天的 X-bar/R 對偶管制圖（含 WECO highlight）" },
  { cat: "spc", ico: "🪜", key: "spc-multi-step",
    title: "多站 xbar 趨勢分頁",
    desc: "同一台機台跨多個 STEP 的 xbar 趨勢，按 step 分頁顯示",
    tpl: "EQP-01 過去 7 天 STEP_001、STEP_002、STEP_003 三站 xbar 趨勢分頁顯示" },
  { cat: "spc", ico: "📦", key: "spc-tool-box",
    title: "各 lot xbar 分佈 box plot",
    desc: "看每個 lot 的 xbar 分佈差異",
    tpl: "EQP-01 STEP_001 過去 7 天各 lot 的 xbar 分佈 box plot" },
  { cat: "spc", ico: "🔬", key: "spc-normality",
    title: "xbar 常態性檢定",
    desc: "Q-Q plot 看數據是否符合常態分佈（給 Cpk 鋪底）",
    tpl: "EQP-01 STEP_001 過去 7 天 xbar 常態性檢定 Q-Q plot" },
  { cat: "spc", ico: "📉", key: "spc-cusum",
    title: "EWMA-CUSUM 漂移偵測",
    desc: "抓 <1σ 的小幅製程漂移",
    tpl: "EQP-01 STEP_001 過去 14 天 EWMA-CUSUM 漂移偵測（k=0.5, h=4）" },

  // ── APC (retained — apc-drift OK; corr/recipe removed) ──────────────
  { cat: "apc", ico: "📐", key: "apc-drift",
    title: "APC 參數漂移檢查",
    desc: "看 etch_time_offset 等 APC 參數最近是否有 drift",
    tpl: "看 [EQP-01] APC etch_time_offset 最近 24 小時是否有漂移" },

  // ── APC (new, audit 2026-05-22 — all built OK) ──────────────────────
  { cat: "apc", ico: "📈", key: "apc-trend",
    title: "APC 參數 24h 趨勢",
    desc: "單一 APC 參數時序 line chart",
    tpl: "EQP-01 過去 24 小時 APC etch_time_offset 趨勢 line chart" },
  { cat: "apc", ico: "🧪", key: "apc-recipe-compare",
    title: "Recipe 別 APC 分佈對比",
    desc: "每個 recipe 跑出的 APC 參數分佈 box plot 對比",
    tpl: "EQP-01 過去 14 天每個 recipe 的 APC etch_time_offset 分佈 box plot 對比" },

  // ── 巡檢 — patrol-status retained; alarm-related all removed ────────
  { cat: "patrol", ico: "🩹", key: "patrol-status",
    title: "機台狀態快照",
    desc: "列各機台目前 idle / processing / down 狀態",
    tpl: "現在所有機台的狀態快照，標示異常的機台" },

  // ── 巡檢 (new, audit 2026-05-22 — all built OK with chart) ──────────
  // Prompts intentionally hint "用 block_groupby_agg 依 X 分組計數" to keep
  // the agent on the groupby-then-chart path instead of falling into
  // block_mcp_foreach over the tool catalog.
  { cat: "patrol", ico: "🏆", key: "ooc-ranking",
    title: "OOC 機台排名 bar chart",
    desc: "依 toolID 分組計數 OOC 事件，畫由多到少",
    tpl: "EQP-01 EQP-02 EQP-03 過去 7 天 SPC 事件，用 block_groupby_agg 依 toolID 分組計數 OOC 事件，畫 bar chart 由多到少" },
  { cat: "patrol", ico: "📊", key: "ooc-pareto",
    title: "OOC chart 別 Pareto",
    desc: "依 SPC chart_name 分組計數，看哪幾種 chart 出 OOC 最多",
    tpl: "EQP-01 過去 7 天 SPC OOC 事件，用 block_groupby_agg 依 chart_name 分組計數，畫 bar chart 由多到少" },
  { cat: "patrol", ico: "🪜", key: "step-yield",
    title: "各 STEP OOC 數 bar chart",
    desc: "看哪個 STEP 是異常熱點",
    tpl: "EQP-01 過去 7 天各 STEP 的 OOC 事件數，依 step 分組計數，畫 bar chart" },
];

interface Props {
  /** Open whenever input starts with "/". Parent passes the filter (text after slash). */
  open: boolean;
  filter: string;
  onPick: (cmd: SlashCommand) => void;
  onClose: () => void;
  /** Lets the parent know the keyboard listener is engaged so the textarea
   *  doesn't double-handle ↑/↓/Enter/Esc when the menu is open. */
  registerKeyHandler?: (h: (e: React.KeyboardEvent | KeyboardEvent) => boolean) => void;
}

export default function SlashCommandMenu({
  open, filter, onPick, onClose, registerKeyHandler,
}: Props) {
  const [hlIdx, setHlIdx] = useState(0);
  const listRef = useRef<HTMLDivElement | null>(null);

  const filtered = useMemo(() => {
    const f = filter.trim().toLowerCase();
    if (!f) return SLASH_COMMANDS;
    return SLASH_COMMANDS.filter((c) =>
      c.title.toLowerCase().includes(f)
      || c.key.toLowerCase().includes(f)
      || c.desc.toLowerCase().includes(f)
    );
  }, [filter]);

  // Reset highlight to first item whenever filter changes / menu opens.
  useEffect(() => { setHlIdx(0); }, [filter, open]);

  // Scroll highlighted item into view.
  useEffect(() => {
    if (!open) return;
    const el = listRef.current?.querySelector<HTMLElement>(`[data-idx="${hlIdx}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [hlIdx, open]);

  // Expose a key handler for the parent's textarea to call.
  useEffect(() => {
    if (!registerKeyHandler) return;
    registerKeyHandler((e) => {
      if (!open) return false;
      if (e.key === "ArrowDown") {
        setHlIdx((i) => Math.min(i + 1, filtered.length - 1));
        return true;
      }
      if (e.key === "ArrowUp") {
        setHlIdx((i) => Math.max(i - 1, 0));
        return true;
      }
      if (e.key === "Enter") {
        const cmd = filtered[hlIdx];
        if (cmd) onPick(cmd);
        return true;
      }
      if (e.key === "Escape") {
        onClose();
        return true;
      }
      return false;
    });
  }, [open, filtered, hlIdx, onPick, onClose, registerKeyHandler]);

  if (!open) return null;

  // Group filtered commands by category, preserving CATEGORIES order.
  const groups = SLASH_CATEGORIES
    .map((g) => ({ ...g, items: filtered.filter((c) => c.cat === g.key) }))
    .filter((g) => g.items.length > 0);

  // Build an index map from filtered position → flattened menu position so
  // ↑/↓ navigation works across groups.
  let cursor = 0;
  return (
    <div
      ref={listRef}
      style={{
        position: "absolute",
        bottom: 84,
        left: 12,
        right: 12,
        maxHeight: 280,
        overflowY: "auto",
        background: "#fff",
        border: "1px solid #d1d5db",
        borderRadius: 8,
        boxShadow: "0 8px 24px rgba(15,23,42,.12)",
        zIndex: 50,
        fontSize: 13,
      }}
    >
      {groups.length === 0 && (
        <div style={{ padding: 14, color: "#94a3b8", textAlign: "center", fontSize: 12 }}>
          找不到符合「{filter}」的指令
        </div>
      )}
      {groups.map((g) => (
        <div key={g.key}>
          <div
            style={{
              fontSize: 10,
              color: "#94a3b8",
              letterSpacing: ".06em",
              textTransform: "uppercase",
              fontWeight: 700,
              padding: "8px 12px 4px",
              background: "#f8fafc",
              position: "sticky",
              top: 0,
            }}
          >
            {g.label}
          </div>
          {g.items.map((it) => {
            const idx = cursor++;
            const hl = idx === hlIdx;
            return (
              <div
                key={it.key}
                data-idx={idx}
                onMouseEnter={() => setHlIdx(idx)}
                onMouseDown={(e) => { e.preventDefault(); onPick(it); }}
                style={{
                  padding: "8px 12px",
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  cursor: "pointer",
                  background: hl ? "#eff6ff" : "transparent",
                  borderBottom: "1px solid #f1f5f9",
                }}
              >
                <span style={{ fontSize: 16, flexShrink: 0 }}>{it.ico}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 500, color: "#1f2937" }}>{it.title}</div>
                  <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 1 }}>{it.desc}</div>
                </div>
                <span
                  style={{
                    fontFamily: "ui-monospace, SFMono-Regular, monospace",
                    fontSize: 10,
                    color: "#2563eb",
                    background: "#eff6ff",
                    padding: "1px 6px",
                    borderRadius: 4,
                    flexShrink: 0,
                  }}
                >
                  /{it.key}
                </span>
              </div>
            );
          })}
        </div>
      ))}
      <div
        style={{
          padding: "6px 12px",
          borderTop: "1px solid #f1f5f9",
          background: "#f8fafc",
          fontSize: 11,
          color: "#94a3b8",
          textAlign: "right",
        }}
      >
        ↑↓ 選 · Enter 套用 · Esc 取消
      </div>
    </div>
  );
}
