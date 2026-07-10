"use client";

/**
 * MCP 能力管理頁 (MCP-registry Phase 3, IT_ADMIN).
 *
 * 一頁列出 agent 的所有能力（內建工具 + domain skill + external），每個標
 * type + 是否寫入 DB，並讓 IT admin 一鍵切 public(對外 cowork) / private(只給
 * 內部 agent)。吃 Phase 2a 的 /api/mcp-capabilities catalog。
 */
import { useCallback, useEffect, useMemo, useState } from "react";

interface Capability {
  key: string;
  name: string;
  description: string;
  kind: "builtin" | "domain_skill" | "external";
  is_write: boolean;
  is_public: boolean;
  is_internal: boolean;
  coordinator_eligible: boolean;
}

const KIND_LABEL: Record<Capability["kind"], string> = {
  builtin: "內建工具",
  domain_skill: "Domain Skill",
  external: "External",
};
const KIND_COLOR: Record<Capability["kind"], string> = {
  builtin: "var(--p, #4F46E5)",
  domain_skill: "#0891B2",
  external: "#B7791F",
};
const KIND_ORDER: Capability["kind"][] = ["builtin", "domain_skill", "external"];

export default function McpRegistryPage() {
  const [caps, setCaps] = useState<Capability[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const r = await fetch("/api/mcp-capabilities", { cache: "no-store" });
      const d = await r.json();
      if (!r.ok) throw new Error(d?.error?.message || `載入失敗 (${r.status})`);
      setCaps(Array.isArray(d) ? d : d.data ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "載入失敗");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = useCallback(async (c: Capability, axis: "public" | "internal") => {
    setBusy(c.key + axis);
    const field = axis === "public" ? "is_public" : "is_internal";
    const cur = axis === "public" ? c.is_public : c.is_internal;
    const next = !cur;
    setCaps((prev) => prev.map((x) => (x.key === c.key ? { ...x, [field]: next } : x)));
    try {
      const r = await fetch(`/api/mcp-capabilities/${encodeURIComponent(c.key)}/exposure`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: c.kind, [field]: next }),
      });
      if (!r.ok) throw new Error();
    } catch {
      setCaps((prev) => prev.map((x) => (x.key === c.key ? { ...x, [field]: cur } : x)));
      setError(`切換 ${c.key} 失敗`);
    } finally {
      setBusy(null);
    }
  }, []);

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return caps;
    return caps.filter(
      (c) => c.key.toLowerCase().includes(s) || (c.description || "").toLowerCase().includes(s),
    );
  }, [caps, q]);

  const stats = useMemo(() => {
    const total = caps.length;
    const publicN = caps.filter((c) => c.is_public).length;
    const writeN = caps.filter((c) => c.is_write).length;
    const internalN = caps.filter((c) => c.is_internal).length;
    return { total, publicN, privateN: total - publicN, writeN, internalN };
  }, [caps]);

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", padding: "28px 24px 80px", color: "#1a1d23" }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 750, margin: 0, letterSpacing: "-0.3px" }}>MCP 能力管理</h1>
          <p style={{ fontSize: 13.5, color: "#5a6473", margin: "6px 0 0" }}>
            每個能力兩個開關：<b>對外</b>(cowork public/private) 與 <b>對內</b>(給我們的 Coordinator agent)。
            建置工具標「僅 Builder」不開對內，以免 Coordinator 繞過 Planner &amp; Builder。
          </p>
        </div>
        <button onClick={() => void load()} disabled={loading}
          style={{ fontSize: 12.5, padding: "7px 14px", borderRadius: 8, border: "1px solid #d7dbe2", background: "#fff", cursor: "pointer", color: "#334" }}>
          {loading ? "載入中…" : "重新整理"}
        </button>
      </div>

      <div style={{ display: "flex", gap: 10, margin: "18px 0 16px", flexWrap: "wrap" }}>
        <Stat k={stats.total} l="能力總數" />
        <Stat k={stats.publicN} l="對外 public" c="#157F52" />
        <Stat k={stats.internalN} l="對內給 agent" c="#2C5AA8" />
        <Stat k={stats.writeN} l="寫入 DB（需確認）" c="#9A6700" />
      </div>

      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜尋能力名稱 / 說明…"
        style={{ width: "100%", boxSizing: "border-box", padding: "9px 13px", fontSize: 13.5, borderRadius: 9, border: "1px solid #dfe3e9", marginBottom: 18, outline: "none" }} />

      {error && <div style={{ padding: "10px 14px", background: "#FBE9E4", color: "#B91C1C", borderRadius: 9, fontSize: 13, marginBottom: 14 }}>{error}</div>}

      {KIND_ORDER.map((kind) => {
        const rows = filtered.filter((c) => c.kind === kind);
        if (rows.length === 0) return null;
        return (
          <div key={kind} style={{ marginBottom: 26 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "0 0 10px" }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: "#fff", background: KIND_COLOR[kind], padding: "3px 9px", borderRadius: 6, letterSpacing: 0.3 }}>
                {KIND_LABEL[kind]}
              </span>
              <span style={{ fontSize: 12, color: "#8a93a2" }}>{rows.length} 個</span>
            </div>
            <div style={{ border: "1px solid #e3e7ed", borderRadius: 12, overflow: "hidden", background: "#fff" }}>
              {rows.map((c, i) => (
                <div key={c.key} style={{ display: "flex", alignItems: "center", gap: 12, padding: "11px 15px", borderTop: i === 0 ? "none" : "1px solid #eef1f5" }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <code style={{ fontFamily: "ui-monospace,Menlo,monospace", fontSize: 12.5, fontWeight: 650 }}>{c.key}</code>
                      {c.is_write && <span title="寫入 DB，呼叫時需人確認" style={{ fontSize: 10, fontWeight: 700, color: "#9A6700", background: "#FBF1DC", padding: "1px 6px", borderRadius: 5 }}>寫入・需確認</span>}
                    </div>
                    <div style={{ fontSize: 12, color: "#6b7280", marginTop: 3, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 640 }}>
                      {(c.description || "").split("\n")[0]}
                    </div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flex: "none" }}>
                    <span style={{ fontSize: 10, color: "#9aa0b4" }}>對外</span>
                    <button onClick={() => void toggle(c, "public")} disabled={busy === c.key + "public"}
                      title={c.is_public ? "點擊改為 private（不對外）" : "點擊改為 public（對外開放給 cowork）"}
                      style={{
                        fontSize: 12, fontWeight: 700, padding: "5px 12px", borderRadius: 20, cursor: "pointer",
                        border: "1px solid " + (c.is_public ? "#B7E1C6" : "#E7C3BB"),
                        background: c.is_public ? "#E7F4EC" : "#FBE9E4",
                        color: c.is_public ? "#157F52" : "#C0341B", minWidth: 84,
                        opacity: busy === c.key + "public" ? 0.5 : 1,
                      }}>
                      {c.is_public ? "public" : "private"}
                    </button>
                    <span style={{ fontSize: 10, color: "#9aa0b4", marginLeft: 4 }}>對內</span>
                    {c.coordinator_eligible ? (
                      <button onClick={() => void toggle(c, "internal")} disabled={busy === c.key + "internal"}
                        title={c.is_internal ? "點擊收回：內部 Coordinator 不再能用" : "點擊給內部 Coordinator 使用（跑現成 / 查詢，不會搶 Builder 的建圖工作）"}
                        style={{
                          fontSize: 12, fontWeight: 700, padding: "5px 12px", borderRadius: 20, cursor: "pointer",
                          border: "1px solid " + (c.is_internal ? "#B7C6E1" : "#dfe3e9"),
                          background: c.is_internal ? "#E6EEFB" : "#F4F5F8",
                          color: c.is_internal ? "#2C5AA8" : "#9aa0b4", minWidth: 84,
                          opacity: busy === c.key + "internal" ? 0.5 : 1,
                        }}>
                        {c.is_internal ? "agent ✓" : "給 agent"}
                      </button>
                    ) : c.kind === "domain_skill" ? (
                      <span title="Skill 是 agent 的預設彈藥庫，一律可用（走 invoke_skill），不需授權"
                        style={{ fontSize: 11, color: "#2C5AA8", minWidth: 84, textAlign: "center", padding: "5px 0" }}>
                        預設可用
                      </span>
                    ) : c.kind === "external" ? (
                      <span title="External MCP 只透過它 V54 產生的 Skill 給 agent 用；沒產生 Skill 就不給。到 System MCP 頁勾「連動產生」"
                        style={{ fontSize: 11, color: "#9aa0b4", minWidth: 84, textAlign: "center", padding: "5px 0" }}>
                        需先產生 Skill
                      </span>
                    ) : (
                      <span title="這是建置工具，只給 Builder；不開放給 Coordinator，以免它繞過 Planner & Builder"
                        style={{ fontSize: 11, color: "#c0c4d0", minWidth: 84, textAlign: "center", padding: "5px 0" }}>
                        僅 Builder
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      })}

      {!loading && caps.length === 0 && !error && (
        <div style={{ padding: 40, textAlign: "center", color: "#8a93a2", fontSize: 14 }}>沒有能力（MCP server 可能未啟動）</div>
      )}
    </div>
  );
}

function Stat({ k, l, c }: { k: number; l: string; c?: string }) {
  return (
    <div style={{ border: "1px solid #e3e7ed", borderRadius: 11, padding: "12px 16px", background: "#fff", minWidth: 120 }}>
      <div style={{ fontSize: 23, fontWeight: 750, lineHeight: 1, color: c ?? "#191c22" }}>{k}</div>
      <div style={{ fontSize: 12, color: "#5a6473", marginTop: 5 }}>{l}</div>
    </div>
  );
}
