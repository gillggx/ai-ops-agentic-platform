"use client";

/**
 * SkillActivateConfirmCard (F4, 2026-07-10).
 *
 * The chat agent's activate_skill tool emits this card instead of writing:
 * name + description are EDITABLE here (prefilled from the agent's suggestion
 * / the built pipeline / the user's original prompt), and only the user's
 * 確認啟用 click performs the writes — in the browser, under the user's auth:
 *   no slug:  POST /api/skills-v2/with-pipeline (create draft) → activate
 *   has slug: PUT  /api/skills-v2/{slug} (apply edited name/nl) → activate
 * Same write-confirm model as AutomationConfirmCard / handoff pages.
 */
import { useEffect, useState } from "react";

export interface SkillParamCandidate {
  name: string;
  type: string;
  label: string;
  description: string;
  default: unknown;
  sites: Array<{ node: string; param: string }>;
  conflicting_values?: unknown[];
}

export interface SkillActivateConfirmData {
  slug?: string | null;
  suggested_name?: string | null;
  suggested_description?: string | null;
  pipeline_json?: Record<string, unknown> | null;
  /** 參數化 (2026-07-10): deterministic scan of hardcoded source identity
   *  params — checked candidates get upgraded to $inputs before create. */
  param_candidates?: SkillParamCandidate[];
  /** AIAgentPanel threads the user's original prompt as a description fallback. */
  goal?: string;
  /** 跨裝置一致 (2026-07-12)：處理結果隨 rich history 同步，別台裝置不能再按。 */
  resolved?: "done" | "cancelled";
  resolvedSlug?: string;
  resolvedName?: string;
}

export function SkillActivateConfirmCard({ data, onResolved }: {
  data: SkillActivateConfirmData;
  onResolved?: (patch: { resolved: "done" | "cancelled"; resolvedSlug?: string; resolvedName?: string }) => void;
}) {
  const [name, setName] = useState(
    data.resolvedName || data.suggested_name || (data.pipeline_json?.name as string) || "");
  const [desc, setDesc] = useState(data.suggested_description || data.goal || "");
  const [state, setState] = useState<"idle" | "working" | "done" | "cancelled" | "error">(data.resolved ?? "idle");
  const [msg, setMsg] = useState("");
  const [doneSlug, setDoneSlug] = useState(data.resolvedSlug ?? "");
  const candidates = data.param_candidates ?? [];
  // 裁決 (2026-07-10): 無衝突的預設全勾（有預設值，行為不變）；同 key 不同值
  // 的衝突候選預設不勾，勾了就統一成一個欄位。
  const [accepted, setAccepted] = useState<Set<string>>(
    () => new Set(candidates.filter((c) => !c.conflicting_values?.length).map((c) => c.name)));

  // Existing skill: prefill from the real row (name / nl) if the agent gave none.
  useEffect(() => {
    if (!data.slug) return;
    fetch(`/api/skills-v2/${encodeURIComponent(data.slug)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((env) => {
        const s = env?.data ?? env;
        if (!s) return;
        setName((prev) => prev || s.name || "");
        setDesc((prev) => prev || s.nl || "");
      })
      .catch(() => { /* prefill only — form still editable */ });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.slug]);

  const confirm = async () => {
    const finalName = name.trim();
    if (!finalName) { setMsg("名稱不能空白"); return; }
    setState("working"); setMsg("");
    try {
      let slug = data.slug || "";
      if (!slug) {
        if (!data.pipeline_json) throw new Error("沒有可啟用的 pipeline");
        let pj = data.pipeline_json;
        const accept = candidates.filter((c) => accepted.has(c.name)).map((c) => c.name);
        if (accept.length > 0) {
          const rp = await fetch("/api/pipeline/parameterize", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ pipeline_json: pj, accept }),
          });
          const pe = await rp.json().catch(() => ({}));
          if (!rp.ok) throw new Error(pe?.detail || pe?.error || "參數化失敗");
          if (!pe?.pipeline_json) throw new Error("參數化回傳異常");
          pj = pe.pipeline_json;
        }
        const r = await fetch("/api/skills-v2/with-pipeline", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: finalName, nl: desc.trim(), sub: desc.trim().slice(0, 60),
            pipeline_json: pj, pipeline_kind: "skill",
          }),
        });
        const env = await r.json();
        if (!r.ok) throw new Error(env?.error?.message || "存成 Skill 失敗");
        slug = (env?.data ?? env)?.skill?.slug;
        if (!slug) throw new Error("找不到 Skill slug");
      } else {
        const r = await fetch(`/api/skills-v2/${encodeURIComponent(slug)}`, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: finalName, nl: desc.trim() }),
        });
        if (!r.ok) {
          const env = await r.json().catch(() => ({}));
          throw new Error(env?.error?.message || "更新名稱失敗");
        }
      }
      const ra = await fetch(`/api/skills-v2/${encodeURIComponent(slug)}/activate`, { method: "POST" });
      if (!ra.ok) {
        const env = await ra.json().catch(() => ({}));
        throw new Error(env?.error?.message || "啟用失敗");
      }
      setDoneSlug(slug);
      setState("done");
      onResolved?.({ resolved: "done", resolvedSlug: slug, resolvedName: finalName });
    } catch (e) {
      setState("error");
      setMsg(e instanceof Error ? e.message : "失敗");
    }
  };

  if (state === "done") {
    return (
      <div style={box}>
        <div style={{ padding: "12px 15px", fontSize: 12.5, color: "#166534", background: "#f0fdf4" }}>
          已啟用「{name.trim()}」— 開始生效。
          <a href={`/skills/${encodeURIComponent(doneSlug)}`}
             target="_blank" rel="noreferrer"
             style={{ marginLeft: 8, color: "var(--p, #2b6cb0)", fontWeight: 600 }}>
            查看 Skill
          </a>
        </div>
      </div>
    );
  }
  if (state === "cancelled") {
    return (
      <div style={box}>
        <div style={{ padding: "10px 15px", fontSize: 12, color: "#94a3b8" }}>已取消啟用。</div>
      </div>
    );
  }

  return (
    <div style={box}>
      <div style={{ padding: "12px 15px", borderBottom: "1px solid #EEF2F6", background: "var(--pn, #F8FAFC)" }}>
        <div style={{ fontSize: 13.5, fontWeight: 700 }}>啟用 Skill — 先確認名稱與描述</div>
        <div style={{ fontSize: 11.5, color: "#64748B", marginTop: 2 }}>
          確認後才會啟用；名稱之後也能在 Skill 頁修改。
        </div>
      </div>
      <div style={{ padding: "12px 15px", display: "flex", flexDirection: "column", gap: 10 }}>
        <label style={lbl}>
          名稱
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={60}
                 placeholder="例：EQP-01 OOC 次數檢查" style={inp} />
        </label>
        <label style={lbl}>
          描述（這個 Skill 做什麼、什麼時候用）
          <textarea value={desc} onChange={(e) => setDesc(e.target.value)} rows={2} style={{ ...inp, resize: "vertical" }} />
        </label>
        {candidates.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "#64748B" }}>
              可變欄位 — 勾選的值以後每次執行都能換（未勾 = 永遠固定）
            </div>
            {candidates.map((c) => {
              const on = accepted.has(c.name);
              const conflict = (c.conflicting_values?.length ?? 0) > 0;
              return (
                <label key={c.name} style={{
                  display: "flex", alignItems: "flex-start", gap: 8,
                  padding: "7px 10px", borderRadius: 8, cursor: "pointer",
                  border: `1px solid ${on ? "var(--p, #2b6cb0)" : "#E2E8F0"}`,
                  background: on ? "var(--pl, #f0f7ff)" : "#fff",
                }}>
                  <input type="checkbox" checked={on} style={{ marginTop: 2 }}
                    onChange={() => setAccepted((prev) => {
                      const next = new Set(prev);
                      if (next.has(c.name)) next.delete(c.name); else next.add(c.name);
                      return next;
                    })} />
                  <span style={{ fontSize: 12, color: "#0f172a", lineHeight: 1.5 }}>
                    <b>{c.label}</b>
                    <span style={{ color: "#64748B" }}>（預設 {String(c.default)}）</span>
                    {conflict && (
                      <span style={{ display: "block", fontSize: 11, color: "#B45309" }}>
                        [note] 圖裡有多個不同值（{c.conflicting_values!.map(String).join("、")}）—
                        勾選後會統一成同一個欄位
                      </span>
                    )}
                  </span>
                </label>
              );
            })}
          </div>
        )}
      </div>
      {msg && <div style={{ padding: "0 15px 8px", fontSize: 12, color: "#B91C1C" }}>{msg}</div>}
      <div style={{ padding: "11px 15px", borderTop: "1px solid #EEF2F6", display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button onClick={() => { setState("cancelled"); onResolved?.({ resolved: "cancelled" }); }} disabled={state === "working"}
          style={{ fontSize: 12.5, padding: "7px 14px", borderRadius: 8,
            border: "1px solid #E2E8F0", background: "#fff", color: "#475569", cursor: "pointer" }}>
          取消
        </button>
        <button onClick={confirm} disabled={state === "working"}
          style={{ fontSize: 12.5, padding: "7px 16px", borderRadius: 8, border: "none",
            background: "var(--p, #2b6cb0)", color: "#fff", fontWeight: 700, cursor: "pointer" }}>
          {state === "working" ? "啟用中…" : "確認啟用"}
        </button>
      </div>
    </div>
  );
}

const box: React.CSSProperties = {
  maxWidth: 420, border: "1px solid #E2E8F0", borderRadius: 12,
  overflow: "hidden", background: "#fff",
};
const lbl: React.CSSProperties = {
  display: "flex", flexDirection: "column", gap: 4,
  fontSize: 11, fontWeight: 600, color: "#64748B",
};
const inp: React.CSSProperties = {
  fontSize: 13, padding: "7px 10px", borderRadius: 7,
  border: "1px solid #E2E8F0", color: "#0f172a", outline: "none",
};
