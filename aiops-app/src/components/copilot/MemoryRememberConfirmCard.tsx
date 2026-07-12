"use client";

/**
 * MemoryRememberConfirmCard (2026-07-12, Memory v1) — agent 提議記住一條偏好；
 * 使用者可改「索引行」（未來唯一召回線索）與內文，按確認後由瀏覽器以本人 JWT
 * POST /api/agent-knowledge 寫入（memo_class='preference'，立即生效）。
 */
import { useState } from "react";

export interface MemoryRememberData {
  index_line: string;
  body: string;
  applies_to: "plan" | "execute" | "both";
  /** 跨裝置一致：處理結果隨 rich history 同步。 */
  resolved?: "done" | "cancelled";
}

const APPLIES_LABEL: Record<string, string> = {
  plan: "建圖時", execute: "回答呈現", both: "都適用",
};

export function MemoryRememberConfirmCard({ data, onResolved }: {
  data: MemoryRememberData;
  onResolved?: (state: "done" | "cancelled") => void;
}) {
  const [state, setState] = useState<"idle" | "working" | "done" | "cancelled" | "error">(data.resolved ?? "idle");
  const [indexLine, setIndexLine] = useState(data.index_line);
  const [body, setBody] = useState(data.body);
  const [appliesTo, setAppliesTo] = useState<MemoryRememberData["applies_to"]>(data.applies_to ?? "both");
  const [msg, setMsg] = useState("");

  const confirm = async () => {
    if (!indexLine.trim() || !body.trim()) { setMsg("索引行與內文都不能空白"); return; }
    setState("working"); setMsg("");
    try {
      const res = await fetch("/api/agent-knowledge", {
        method: "POST", headers: { "Content-Type": "application/json" },
        // Java wire = snake_case（camelCase 會被靜默忽略成 null）
        body: JSON.stringify({
          scope_type: "global", title: indexLine.trim(), body: body.trim(),
          priority: "med", memo_class: "preference", applies_to: appliesTo,
        }),
      });
      if (!res.ok) {
        const env = await res.json().catch(() => ({}));
        throw new Error(env?.error?.message || `HTTP ${res.status}`);
      }
      setState("done");
      onResolved?.("done");
    } catch (e) {
      setState("error"); setMsg(e instanceof Error ? e.message : "寫入失敗");
    }
  };

  if (state === "done") {
    return <div style={box}><div style={{ padding: "11px 15px", fontSize: 12.5, color: "#166534", background: "#f0fdf4" }}>
      已記住：「{indexLine}」 — 之後的對話會自動帶入（可隨時問「你記得我什麼」或叫我忘掉）。</div></div>;
  }
  if (state === "cancelled") {
    return <div style={box}><div style={{ padding: "10px 15px", fontSize: 12, color: "#94a3b8" }}>已取消，不記了。</div></div>;
  }

  return (
    <div style={box}>
      <div style={{ padding: "11px 15px", borderBottom: "1px solid #EEF2F6", background: "var(--pl, #F8FAFC)" }}>
        <div style={{ fontSize: 13.5, fontWeight: 700 }}>記住這條偏好？</div>
        <div style={{ fontSize: 11.5, color: "#64748B", marginTop: 2 }}>
          索引行是它未來想起這件事的唯一線索——建議寫「什麼情境該想起」。
        </div>
      </div>
      <div style={{ padding: "10px 15px", display: "flex", flexDirection: "column", gap: 8 }}>
        <label style={{ fontSize: 11, fontWeight: 700, color: "#64748B" }}>索引行（召回線索）
          <input value={indexLine} onChange={(e) => setIndexLine(e.target.value)} maxLength={80}
            style={{ width: "100%", marginTop: 3, padding: "7px 10px", borderRadius: 8,
                     border: "1px solid #E2E8F0", fontSize: 13, boxSizing: "border-box" }} />
        </label>
        <label style={{ fontSize: 11, fontWeight: 700, color: "#64748B" }}>完整內容
          <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={3} maxLength={2000}
            style={{ width: "100%", marginTop: 3, padding: "7px 10px", borderRadius: 8,
                     border: "1px solid #E2E8F0", fontSize: 12.5, resize: "vertical",
                     fontFamily: "inherit", boxSizing: "border-box" }} />
        </label>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: "#64748B" }}>適用</span>
          {(["both", "plan", "execute"] as const).map((k) => (
            <button key={k} onClick={() => setAppliesTo(k)}
              style={{ fontSize: 11.5, padding: "4px 10px", borderRadius: 12, cursor: "pointer",
                       border: appliesTo === k ? "1px solid var(--p, #1E5A44)" : "1px solid #E2E8F0",
                       background: appliesTo === k ? "var(--pl, #E4EEE7)" : "#fff",
                       color: appliesTo === k ? "var(--pd, #14402F)" : "#475569",
                       fontWeight: appliesTo === k ? 700 : 400 }}>
              {APPLIES_LABEL[k]}
            </button>
          ))}
        </div>
      </div>
      {msg && <div style={{ padding: "0 15px 6px", fontSize: 12, color: "#B91C1C" }}>{msg}</div>}
      <div style={{ padding: "10px 15px", borderTop: "1px solid #EEF2F6", display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button onClick={() => { setState("cancelled"); onResolved?.("cancelled"); }} disabled={state === "working"}
          style={{ fontSize: 12.5, padding: "7px 14px", borderRadius: 8, border: "1px solid #E2E8F0",
                   background: "#fff", color: "#475569", cursor: "pointer" }}>取消</button>
        <button onClick={() => void confirm()} disabled={state === "working"}
          style={{ fontSize: 12.5, padding: "7px 16px", borderRadius: 8, border: "none",
                   background: "var(--p, #1E5A44)", color: "#fff", fontWeight: 700, cursor: "pointer" }}>
          {state === "working" ? "寫入中…" : "確認記住"}
        </button>
      </div>
    </div>
  );
}

const box: React.CSSProperties = { maxWidth: 460, border: "1px solid #E2E8F0", borderRadius: 12, overflow: "hidden", background: "#fff" };
