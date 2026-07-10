"use client";

/**
 * 手機 4c 手冊 — Knowledge / Lexicon / Examples 條目卡直排（active 群組在上、
 * draft 在下）＋搜尋。資料走既有 /api/agent-knowledge、/api/agent-lexicon、
 * /api/agent-examples。
 */
import { useEffect, useMemo, useState } from "react";
import { M, cardStyle } from "./tokens";

interface Knowledge {
  id: number; title: string; body: string; active: boolean; status: string | null;
  memo_class: string | null; scope_type: string; uses: number;
  last_used_at: string | null;
}
interface Lexicon { id: number; term: string; standard: string; note: string; uses: number }
interface Example { id: number; title: string; scope_type: string; uses: number }

const CLASS_BADGE: Record<string, { fg: string; bg: string }> = {
  procedure: { fg: "var(--pd, #4338ca)", bg: "var(--pl, #eef0ff)" },
  domain: { fg: "#0f766e", bg: "#d5f5ef" },
  correction: { fg: "#7c3aed", bg: "#f3e8ff" },
};

function dateLabel(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function MobileManual() {
  const [knowledge, setKnowledge] = useState<Knowledge[]>([]);
  const [lexicon, setLexicon] = useState<Lexicon[]>([]);
  const [examples, setExamples] = useState<Example[]>([]);
  const [pill, setPill] = useState<"knowledge" | "lexicon" | "examples">("knowledge");
  const [q, setQ] = useState("");

  useEffect(() => {
    const grab = <T,>(url: string, set: (v: T[]) => void) =>
      fetch(url, { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : null))
        .then((env) => {
          const d = env?.data ?? env;
          if (Array.isArray(d)) set(d as T[]);
        })
        .catch(() => { /* ambient */ });
    void grab<Knowledge>("/api/agent-knowledge", setKnowledge);
    void grab<Lexicon>("/api/agent-lexicon", setLexicon);
    void grab<Example>("/api/agent-examples", setExamples);
  }, []);

  const kShown = useMemo(() => {
    const match = (k: Knowledge) =>
      !q || k.title?.toLowerCase().includes(q.toLowerCase()) || k.body?.toLowerCase().includes(q.toLowerCase());
    const isDraft = (k: Knowledge) => k.status === "draft" || !k.active;
    const rows = knowledge.filter(match);
    return [...rows.filter((k) => !isDraft(k)), ...rows.filter(isDraft)];
  }, [knowledge, q]);

  return (
    <div style={{ padding: "14px 14px 90px", fontFamily: M.sans, color: M.ink }}>
      <div style={{ fontSize: 21, fontWeight: 800 }}>手冊</div>
      <div style={{ fontSize: 11.5, color: M.sub, marginTop: 2 }}>已生效的真理 ・ 來源 Supervisor 蒸餾</div>

      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜尋條目 / How-to-apply…" style={{
        width: "100%", marginTop: 12, padding: "10px 13px", borderRadius: 11,
        border: `1px solid ${M.line}`, background: "#fff", fontSize: 13, color: M.ink, outline: "none",
        boxSizing: "border-box",
      }} />

      <div style={{ display: "flex", gap: 7, margin: "10px 0" }}>
        {([["knowledge", `Knowledge ${knowledge.length}`], ["lexicon", `Lexicon ${lexicon.length}`],
           ["examples", `Examples ${examples.length}`]] as const).map(([k, label]) => (
          <button key={k} onClick={() => setPill(k)} style={{
            border: "none", borderRadius: 16, padding: "6px 12px", fontSize: 12, fontWeight: 700,
            cursor: "pointer",
            background: pill === k ? M.ink : "#fff",
            color: pill === k ? "#fff" : M.sub,
            boxShadow: pill === k ? "none" : `inset 0 0 0 1px ${M.line}`,
          }}>{label}</button>
        ))}
      </div>

      {pill === "knowledge" && kShown.map((k) => {
        const cls = CLASS_BADGE[k.memo_class ?? ""] ?? { fg: M.sub, bg: M.lowBg };
        const draft = k.status === "draft" || !k.active;
        return (
          <div key={k.id} style={{ ...cardStyle, padding: "11px 13px", marginBottom: 8 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <span style={{ fontFamily: M.mono, fontSize: 12, fontWeight: 700 }}>#{k.id}</span>
              {k.memo_class && (
                <span style={{
                  fontSize: 9, fontWeight: 700, fontFamily: M.mono, padding: "1px 7px",
                  borderRadius: 4, color: cls.fg, background: cls.bg,
                }}>{k.memo_class}</span>
              )}
              <span style={{ flex: 1 }} />
              <span style={{
                fontSize: 9, fontWeight: 700, fontFamily: M.mono, padding: "1px 7px", borderRadius: 4,
                color: draft ? "#c2410c" : M.ok, background: draft ? "#fff7ed" : M.okBg,
              }}>{draft ? "draft" : "active"}</span>
            </div>
            <div style={{ fontSize: 13, marginTop: 6, lineHeight: 1.55 }}>
              {k.title || (k.body || "").split("\n")[0]}
            </div>
            <div style={{ fontFamily: M.mono, fontSize: 10.5, color: M.faint, marginTop: 5 }}>
              uses {k.uses ?? 0} ・ 最近召回 {dateLabel(k.last_used_at)}
            </div>
          </div>
        );
      })}

      {pill === "lexicon" && lexicon
        .filter((l) => !q || l.term.toLowerCase().includes(q.toLowerCase()) || l.standard.toLowerCase().includes(q.toLowerCase()))
        .map((l) => (
          <div key={l.id} style={{ ...cardStyle, padding: "11px 13px", marginBottom: 8 }}>
            <div style={{ fontSize: 13, fontWeight: 700 }}>
              {l.term} <span style={{ color: M.faint, fontWeight: 400 }}>→</span> {l.standard}
            </div>
            {l.note && <div style={{ fontSize: 12, color: M.sub, marginTop: 4 }}>{l.note}</div>}
            <div style={{ fontFamily: M.mono, fontSize: 10.5, color: M.faint, marginTop: 4 }}>uses {l.uses ?? 0}</div>
          </div>
        ))}

      {pill === "examples" && (
        examples.length === 0
          ? <div style={{ padding: 24, textAlign: "center", color: M.faint, fontSize: 12.5 }}>還沒有 Examples</div>
          : examples
              .filter((e) => !q || e.title.toLowerCase().includes(q.toLowerCase()))
              .map((e) => (
                <div key={e.id} style={{ ...cardStyle, padding: "11px 13px", marginBottom: 8 }}>
                  <div style={{ fontSize: 13, fontWeight: 700 }}>{e.title}</div>
                  <div style={{ fontFamily: M.mono, fontSize: 10.5, color: M.faint, marginTop: 4 }}>
                    {e.scope_type} ・ uses {e.uses ?? 0}
                  </div>
                </div>
              ))
      )}
    </div>
  );
}
