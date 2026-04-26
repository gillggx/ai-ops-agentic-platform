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

export const SLASH_CATEGORIES: Array<{ key: SlashCommand["cat"]; label: string }> = [
  { key: "spc",    label: "📊 SPC" },
  { key: "apc",    label: "🔧 APC" },
  { key: "patrol", label: "📋 巡檢" },
  { key: "diag",   label: "🩺 診斷" },
];

export const SLASH_COMMANDS: SlashCommand[] = [
  // SPC
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
    title: "多機台同站點 xbar 並排",
    desc: "把同一站不同機台的 SPC 趨勢放一起比較",
    tpl: "把 [EQP-01]~[EQP-05] 在 [STEP_001] 的 xbar 趨勢並排" },

  // APC
  { cat: "apc", ico: "📐", key: "apc-drift",
    title: "APC 參數漂移檢查",
    desc: "看 etch_time_offset 等 APC 參數最近是否有 drift",
    tpl: "看 [EQP-01] APC etch_time_offset 最近 24 小時是否有漂移" },
  { cat: "apc", ico: "🔗", key: "apc-corr",
    title: "APC ↔ SPC 相關性",
    desc: "找 APC 參數變動跟 SPC OOC 之間的相關性",
    tpl: "找 [EQP-01] APC etch_time_offset 跟 SPC xbar OOC 的相關性" },
  { cat: "apc", ico: "🧪", key: "apc-recipe",
    title: "Recipe 切換前後 APC 比較",
    desc: "看 recipe 變更後 APC 參數是否跑掉",
    tpl: "[EQP-01] 在 [recipe X→Y] 切換後 APC 參數有沒有變化？" },

  // 巡檢
  { cat: "patrol", ico: "🔔", key: "patrol-alarms",
    title: "今日 alarm 列表",
    desc: "全廠今日 OPEN 的 HIGH 級告警 + 證據",
    tpl: "列出今天所有 HIGH 級 alarm（OPEN 狀態），含觸發證據" },
  { cat: "patrol", ico: "🩹", key: "patrol-status",
    title: "機台狀態快照",
    desc: "列各機台目前 idle / processing / down 狀態",
    tpl: "現在所有機台的狀態快照，標示異常的機台" },
  { cat: "patrol", ico: "📋", key: "patrol-recipe-consist",
    title: "Recipe 一致性檢查",
    desc: "找出全廠跑同一 recipe 但結果有差異的機台",
    tpl: "全廠跑 recipe [R001] 的機台，xbar 平均值差異 > 1.5σ 的列出來" },

  // 診斷
  { cat: "diag", ico: "🩺", key: "diag-alarm",
    title: "Alarm 根因分析",
    desc: "針對特定 alarm，找出觸發證據 + 可能根因",
    tpl: "Alarm #[id] 根因分析：列觸發條件、證據資料、相關 APC/SPC" },
  { cat: "diag", ico: "🔬", key: "diag-ooc-point",
    title: "OOC 單點深度診斷",
    desc: "選一個 OOC 點，把附近 process 跟 APC 變化都調出來",
    tpl: "[LOT-0234] 在 [EQP-01] [STEP_001] 的 OOC 點，前後 30 分鐘的 APC 變化" },
  { cat: "diag", ico: "🧭", key: "diag-walkback",
    title: "從 alarm 倒推到製程",
    desc: "從 alarm → SPC 點 → APC 紀錄 → recipe，一路追回去",
    tpl: "從 alarm #[id] 倒推：SPC 證據 → APC 紀錄 → 當下 recipe，全部列出" },
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
