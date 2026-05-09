"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Icon, Btn } from "@/components/skills/atoms";

/**
 * /skills/new — minimal author kickoff. Asks for slug + title + stage,
 * creates the skill_document row, then navigates to /skills/[slug]/edit
 * where the user fills trigger + steps.
 */
export default function NewSkillPage() {
  const router = useRouter();
  const [slug, setSlug] = useState("");
  const [title, setTitle] = useState("");
  const [stage, setStage] = useState<"patrol" | "diagnose">("diagnose");
  const [domain, setDomain] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch("/api/skill-documents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug, title, stage, domain }),
      });
      const json = await res.json();
      if (!res.ok || !json.ok) throw new Error(json.error?.message || `HTTP ${res.status}`);
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
          建立一份新的 skill 知識文件。建好後會跳到 Author 頁面填 trigger 與 step。
        </p>

        <div style={{ marginTop: 28, display: "flex", flexDirection: "column", gap: 14 }}>
          <Field label="SLUG" hint="URL-friendly id，e.g. ocap-diag">
            <input value={slug} onChange={(e) => setSlug(e.target.value.replace(/[^a-z0-9-]/gi, "-").toLowerCase())}
              placeholder="ocap-diag"
              className="mono"
              style={{ padding: "8px 10px", border: "1px solid var(--line-strong)", borderRadius: 6,
                       fontSize: 13, background: "var(--surface)", outline: "none", fontFamily: "JetBrains Mono, monospace" }}/>
          </Field>
          <Field label="TITLE">
            <input value={title} onChange={(e) => setTitle(e.target.value)}
              placeholder="OCAP Advanced Diagnostic Playbook"
              style={{ padding: "8px 10px", border: "1px solid var(--line-strong)", borderRadius: 6,
                       fontSize: 14, background: "var(--surface)", outline: "none", fontFamily: "inherit" }}/>
          </Field>
          <Field label="STAGE">
            <div style={{ display: "inline-flex", padding: 2, borderRadius: 8, background: "var(--surface-2)", border: "1px solid var(--line)" }}>
              {(["patrol", "diagnose"] as const).map((s) => (
                <button key={s} onClick={() => setStage(s)} style={{
                  padding: "6px 14px", borderRadius: 6, border: "none",
                  background: stage === s ? "var(--surface)" : "transparent",
                  color: stage === s ? "var(--ink)" : "var(--ink-3)",
                  fontSize: 13, fontWeight: 500, cursor: "pointer",
                }}>{s}</button>
              ))}
            </div>
          </Field>
          <Field label="DOMAIN" hint="optional, e.g. Photo · Etch">
            <input value={domain} onChange={(e) => setDomain(e.target.value)}
              placeholder="Photo · Etch"
              style={{ padding: "8px 10px", border: "1px solid var(--line-strong)", borderRadius: 6,
                       fontSize: 13, background: "var(--surface)", outline: "none", fontFamily: "inherit" }}/>
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
            disabled={submitting || !slug.trim() || !title.trim()}>
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
