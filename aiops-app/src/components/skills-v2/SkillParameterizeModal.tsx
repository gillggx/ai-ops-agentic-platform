"use client";

/**
 * SkillParameterizeModal — 真 Skill 化精靈 (2026-07-08)。
 *
 * 兩步一頁：
 *  1. 開放參數：確定性候選（source 身分參數）勾選清單，預設全勾。
 *  2. 說明書：Haiku 草擬 use_case / when_to_use / tags，人可改。
 * onConfirm 回傳 {pipelineJson(參數化後), doc} — 存檔由呼叫端負責
 * （新 skill 走 with-pipeline、舊 skill 走 PUT /pipeline）。
 */

import { useEffect, useState } from "react";

export interface ParamCandidate {
  name: string;
  type: string;
  label: string;
  description: string;
  default: unknown;
  example: unknown;
  sites: Array<{ node: string; param: string }>;
  conflicting_values?: unknown[];
}

export interface SkillDoc {
  use_case: string;
  when_to_use: string[];
  distinction?: string;
  example_invocation?: Record<string, unknown>;
  tags: string[];
}

interface Props {
  open: boolean;
  skillName: string;
  nl?: string;
  pipelineJson: Record<string, unknown>;
  onClose: () => void;
  onConfirm: (out: { pipelineJson: Record<string, unknown>; doc: SkillDoc | null }) => void;
  confirmLabel?: string;
}

export default function SkillParameterizeModal({
  open, skillName, nl, pipelineJson, onClose, onConfirm, confirmLabel = "儲存",
}: Props) {
  const [cands, setCands] = useState<ParamCandidate[] | null>(null);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [doc, setDoc] = useState<SkillDoc | null>(null);
  const [drafting, setDrafting] = useState(false);
  const [applying, setApplying] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setCands(null); setDoc(null); setErr(null);
    fetch("/api/pipeline-builder/parameterize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pipeline_json: pipelineJson }),
    })
      .then((r) => r.json())
      .then((d) => {
        const list: ParamCandidate[] = d.candidates ?? [];
        setCands(list);
        setChecked(Object.fromEntries(list.map((c) => [c.name, true])));
      })
      .catch((e) => setErr(String(e)));
  }, [open, pipelineJson]);

  if (!open) return null;

  const draftDoc = async () => {
    setDrafting(true); setErr(null);
    try {
      const res = await fetch("/api/pipeline-builder/skill-draft-doc", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: skillName, nl: nl ?? "", pipeline_json: pipelineJson }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(JSON.stringify(d).slice(0, 150));
      setDoc(d.doc as SkillDoc);
    } catch (e) {
      setErr(`說明書草擬失敗：${String(e).slice(0, 120)}`);
    } finally {
      setDrafting(false);
    }
  };

  const confirm = async () => {
    setApplying(true); setErr(null);
    try {
      const accept = Object.entries(checked).filter(([, v]) => v).map(([k]) => k);
      let pj = pipelineJson;
      if (accept.length) {
        const res = await fetch("/api/pipeline-builder/parameterize", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pipeline_json: pipelineJson, accept }),
        });
        const d = await res.json();
        if (!res.ok) throw new Error(JSON.stringify(d).slice(0, 150));
        pj = d.pipeline_json;
      }
      onConfirm({ pipelineJson: pj as Record<string, unknown>, doc });
    } catch (e) {
      setErr(`套用失敗：${String(e).slice(0, 120)}`);
      setApplying(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 80, background: "rgba(15,23,42,.45)",
                  display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ background: "#fff", borderRadius: 12, width: 560, maxHeight: "84vh",
                    overflowY: "auto", padding: "20px 22px", boxShadow: "0 18px 50px rgba(0,0,0,.25)" }}>
        <div style={{ fontSize: 16, fontWeight: 800, marginBottom: 2 }}>把「{skillName}」變成可帶參數的 Skill</div>
        <div style={{ fontSize: 12, color: "#64748b", marginBottom: 14 }}>
          勾選的參數以後呼叫時可以換（沒給就用預設值）；說明書讓 agent 知道何時該用它。
        </div>

        <div style={{ fontSize: 13, fontWeight: 700, margin: "10px 0 6px" }}>1 · 開放哪些參數</div>
        {cands === null && <div style={{ fontSize: 12, color: "#94a3b8" }}>掃描中…</div>}
        {cands !== null && cands.length === 0 && (
          <div style={{ fontSize: 12, color: "#94a3b8" }}>沒有可開放的參數（來源節點沒有寫死的身分參數，或已參數化）。</div>
        )}
        {(cands ?? []).map((c) => (
          <label key={c.name} style={{ display: "flex", gap: 8, alignItems: "flex-start",
                                       padding: "6px 8px", borderRadius: 8,
                                       background: checked[c.name] ? "#f0fdf4" : "transparent" }}>
            <input type="checkbox" checked={!!checked[c.name]}
                   onChange={(e) => setChecked((p) => ({ ...p, [c.name]: e.target.checked }))} />
            <span style={{ fontSize: 12.5 }}>
              <b style={{ fontFamily: "ui-monospace,monospace" }}>{c.name}</b>
              <span style={{ color: "#64748b" }}> — {c.label}，預設 <code>{String(c.default)}</code>
              {c.conflicting_values?.length ? `（多節點值不一致：${c.conflicting_values.join(", ")}）` : ""}</span>
            </span>
          </label>
        ))}

        <div style={{ fontSize: 13, fontWeight: 700, margin: "16px 0 6px" }}>2 · 說明書（agent 選用的依據）</div>
        {!doc && (
          <button onClick={draftDoc} disabled={drafting}
                  style={{ fontSize: 12.5, padding: "6px 14px", borderRadius: 8,
                           border: "1px solid #c7d2fe", background: "#eef2ff", color: "#4338ca",
                           cursor: "pointer" }}>
            {drafting ? "草擬中…" : "用 AI 草擬說明書（可改）"}
          </button>
        )}
        {doc && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <label style={{ fontSize: 11.5, color: "#64748b" }}>做什麼
              <input value={doc.use_case}
                     onChange={(e) => setDoc({ ...doc, use_case: e.target.value })}
                     style={{ width: "100%", fontSize: 12.5, padding: "6px 8px",
                              border: "1px solid #e2e8f0", borderRadius: 6 }} />
            </label>
            <label style={{ fontSize: 11.5, color: "#64748b" }}>什麼時候用它（每行一條）
              <textarea value={(doc.when_to_use ?? []).join("\n")} rows={3}
                        onChange={(e) => setDoc({ ...doc, when_to_use: e.target.value.split("\n").filter(Boolean) })}
                        style={{ width: "100%", fontSize: 12.5, padding: "6px 8px",
                                 border: "1px solid #e2e8f0", borderRadius: 6 }} />
            </label>
            <label style={{ fontSize: 11.5, color: "#64748b" }}>檢索關鍵字（逗號分隔）
              <input value={(doc.tags ?? []).join(", ")}
                     onChange={(e) => setDoc({ ...doc, tags: e.target.value.split(",").map((t) => t.trim()).filter(Boolean) })}
                     style={{ width: "100%", fontSize: 12.5, padding: "6px 8px",
                              border: "1px solid #e2e8f0", borderRadius: 6 }} />
            </label>
          </div>
        )}

        {err && <div style={{ marginTop: 10, fontSize: 12, color: "#b42318" }}>{err}</div>}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 18 }}>
          <button onClick={onClose} style={{ fontSize: 12.5, padding: "7px 16px", borderRadius: 8,
                  border: "1px solid #e2e8f0", background: "#fff", cursor: "pointer" }}>取消</button>
          <button onClick={confirm} disabled={applying || cands === null}
                  style={{ fontSize: 12.5, padding: "7px 16px", borderRadius: 8, border: "none",
                           background: "#4F46E5", color: "#fff", fontWeight: 700, cursor: "pointer" }}>
            {applying ? "套用中…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
