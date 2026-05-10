"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Icon, Btn } from "@/components/skills/atoms";

/**
 * /skills/new — minimal author kickoff. Phase 11 v11: only title +
 * description; slug auto-derived server-side; stage defaults to
 * "diagnose" and flips to "patrol" automatically when Author later
 * sets a schedule trigger. Domain dropped (unused by current UI).
 */
export default function NewSkillPage() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch("/api/skill-documents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, description }),
      });
      const json = await res.json();
      if (!res.ok || !json.ok) throw new Error(json.error?.message || `HTTP ${res.status}`);
      const slug = json.data?.slug;
      if (!slug) throw new Error("backend did not return a slug");
      router.push(`/skills/${encodeURIComponent(slug)}/edit`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="skill-surface">
      <div style={{ maxWidth: 640, margin: "0 auto", padding: "60px 32px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, color: "var(--ink-3)", marginBottom: 16 }}>
          <Link href="/skills">Skills Library</Link>
          <span style={{ color: "var(--ink-4)" }}>/</span>
          <span style={{ color: "var(--ink)", fontWeight: 500 }}>New Skill</span>
        </div>

        <h1 style={{ margin: 0, fontSize: 28, fontWeight: 600, letterSpacing: "-0.015em" }}>
          New Skill Document
        </h1>
        <p style={{ marginTop: 10, fontSize: 13.5, color: "var(--ink-2)", lineHeight: 1.6 }}>
          給這份 skill 一個名稱跟簡短描述就好。建好後跳到 Author 頁面填 trigger 與 step。
          <br/>
          <span style={{ color: "var(--ink-3)", fontSize: 12 }}>
            slug、stage、domain 等技術欄位之後會自動依你的設定 derive，不用手填。
          </span>
        </p>

        <div style={{ marginTop: 28, display: "flex", flexDirection: "column", gap: 14 }}>
          <Field label="TITLE">
            <input value={title} onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. OCAP 進階診斷"
              style={{ padding: "8px 10px", border: "1px solid var(--line-strong)", borderRadius: 6,
                       fontSize: 14, background: "var(--surface)", outline: "none", fontFamily: "inherit" }}/>
          </Field>
          <Field label="DESCRIPTION" hint="（選填）一兩句話讓 Library 列表上的人知道這 skill 在做什麼">
            <textarea value={description} onChange={(e) => setDescription(e.target.value)}
              rows={3}
              placeholder="例：OCAP 觸發後依序檢查歷史 OOC 趨勢、SPC 違規、APC recipe 異動，並提示對應建議行動。"
              style={{ padding: "8px 10px", border: "1px solid var(--line-strong)", borderRadius: 6,
                       fontSize: 13, background: "var(--surface)", outline: "none",
                       fontFamily: "inherit", resize: "vertical", lineHeight: 1.55 }}/>
          </Field>

          {error && (
            <div style={{ padding: "10px 12px", background: "var(--fail-bg)", color: "var(--fail)",
                          border: "1px solid var(--fail)", borderRadius: 6, fontSize: 12.5 }}>
              {error}
            </div>
          )}
        </div>

        <div style={{ marginTop: 24, display: "flex", gap: 8 }}>
          <Btn kind="primary" icon={<Icon.Plus/>} onClick={submit}
            disabled={submitting || !title.trim()}>
            {submitting ? "Creating…" : "Create skill"}
          </Btn>
          <Link href="/skills" style={{
            display: "inline-flex", alignItems: "center", padding: "6px 11px", borderRadius: 6,
            background: "transparent", color: "var(--ink-2)",
            border: "1px solid transparent", fontSize: 12.5, fontWeight: 500, textDecoration: "none",
          }}>Cancel</Link>
        </div>
      </div>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span className="mono" style={{ fontSize: 9.5, letterSpacing: "0.08em", color: "var(--ink-3)" }}>{label}</span>
        {hint && <span style={{ fontSize: 11, color: "var(--ink-4)" }}>{hint}</span>}
      </div>
      {children}
    </div>
  );
}
