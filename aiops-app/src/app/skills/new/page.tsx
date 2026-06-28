"use client";

/**
 * Skills v2 — New Skill wizard.
 *
 * Tiny form: name + slug (auto-slugged from name; editable) + sub + NL.
 * On Create, redirect to /skills/[slug] (Editor) so the author can
 * Re-compile immediately. Skipping pipeline binding for now — the user
 * compiles the NL into pipeline_nodes from the Editor, which is the
 * spec's intended flow.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { TK, FONT, ensurePlexFont } from "@/components/skills-v2/tokens";

export default function NewSkillPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [sub, setSub] = useState("");
  const [nl, setNl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { ensurePlexFont(); }, []);

  const canSubmit = name.trim().length > 0 && !submitting;

  const handleCreate = useCallback(async () => {
    setError(null);
    setSubmitting(true);
    // Slug is an implementation detail (URL only). Auto-generate from
    // name + short random suffix so the user never has to think about
    // collisions or URL-safe encoding. Server still rejects duplicates
    // with 409 so a vanishingly-rare collision retries with new slug.
    const slug = autoSlug(name);
    try {
      const res = await fetch("/api/skills-v2", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug, name: name.trim(), sub: sub.trim(), nl: nl.trim() }),
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || `HTTP ${res.status}`);
      }
      // Route by id (slug is internal). Fall back to slug if id missing.
      const env = await res.json().catch(() => null);
      const created = env?.data ?? env;
      router.push(`/skills/${created?.id ?? encodeURIComponent(slug)}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSubmitting(false);
    }
  }, [name, sub, nl, router]);

  return (
    <div style={{ background: TK.page, minHeight: "100vh", padding: "24px 24px 80px", fontFamily: FONT.sans, color: TK.ink }}>
      <div style={{ maxWidth: 720, margin: "0 auto" }}>
        <div style={{ marginBottom: 12 }}>
          <Link href="/skills" style={{ color: TK.body, fontSize: 13, textDecoration: "none" }}>
            ← Skills Library
          </Link>
        </div>

        <div style={{
          background: TK.card, borderRadius: 14, padding: "22px 26px",
          boxShadow: "0 1px 3px rgba(15,18,30,.06)",
        }}>
          <div style={{
            font: `600 11px ${FONT.mono}`, letterSpacing: ".13em",
            color: TK.faint, textTransform: "uppercase", marginBottom: 6,
          }}>
            新增 SKILL
          </div>
          <h1 style={{ font: `700 22px ${FONT.sans}`, color: TK.ink, margin: "0 0 4px" }}>新增 Skill</h1>
          <p style={{ fontSize: 13, color: TK.body, margin: 0 }}>
            填名稱 + 一句說明 + 自然語言描述，建立後到 Editor 按「重新編譯 ↻」生成 pipeline。
          </p>
        </div>

        <div style={{
          background: TK.card, borderRadius: 14, padding: "22px 26px", marginTop: 14,
          boxShadow: "0 1px 3px rgba(15,18,30,.06)",
        }}>
          <Field label="名稱（顯示用）" required>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例：CD_Mean SPC 5取2 全廠巡檢"
              autoFocus
              style={inputStyle}
            />
          </Field>
          <Field label="一句說明" hint="會出現在 Library 卡片的副標。">
            <input
              value={sub}
              onChange={(e) => setSub(e.target.value)}
              placeholder="例：每 1 小時掃所有機台，5 取 2 達標就 emit Event + ALARM。"
              style={inputStyle}
            />
          </Field>
          <Field label="自然語言描述 · NL" hint="這個 Skill 要做什麼。建立後可在 Editor 改寫並重新編譯。">
            <textarea
              value={nl}
              onChange={(e) => setNl(e.target.value)}
              placeholder="每小時掃所有機台，看最近 5 筆 SPC 紀錄是否有 2 筆以上 OOC..."
              rows={6}
              style={{ ...inputStyle, lineHeight: 1.6, resize: "vertical", fontFamily: FONT.sans }}
            />
          </Field>

          {error && (
            <div style={{
              background: "#fef3f2", color: "#b42318",
              border: "1px solid #fecaca",
              padding: 10, borderRadius: 8, fontSize: 12.5, marginTop: 8,
            }}>{error}</div>
          )}

          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 16, gap: 8 }}>
            <Link href="/skills" style={{
              font: `600 12.5px ${FONT.sans}`,
              color: TK.body, background: "#fff",
              border: `1px solid ${TK.divider}`,
              padding: "9px 14px", borderRadius: 8, textDecoration: "none",
            }}>取消</Link>
            <button
              onClick={handleCreate}
              disabled={!canSubmit}
              style={{
                font: `600 13px ${FONT.sans}`,
                color: "#fff", background: TK.black, border: `1px solid ${TK.black}`,
                padding: "9px 18px", borderRadius: 9,
                cursor: canSubmit ? "pointer" : "not-allowed",
                opacity: canSubmit ? 1 : 0.5,
              }}
            >
              {submitting ? "Creating…" : "建立 → 進 Editor"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── small bits ─────────────────────────────────────────────────────────────

function Field({
  label, hint, required, children,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={{ display: "block", marginBottom: 6, font: `600 12px ${FONT.sans}`, color: TK.ink }}>
        {label}{required && <span style={{ color: "#b42318", marginLeft: 4 }}>*</span>}
      </label>
      {children}
      {hint && <div style={{ marginTop: 4, fontSize: 11, color: TK.faint }}>{hint}</div>}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "8px 10px",
  borderRadius: 8,
  border: `1px solid ${TK.divider}`,
  fontSize: 13,
  fontFamily: FONT.sans,
  color: TK.ink,
  background: "#fff",
  outline: "none",
  boxSizing: "border-box",
};

/**
 * Auto-generate a URL slug from the human name. Strips diacritics/CJK to
 * keep the slug ASCII-safe (browsers tolerate utf-8 but logs / oncall
 * scripts often don't); collisions are extremely unlikely because we
 * append a 4-char random tail. Server still 409s on collision so the
 * rare paranoid case retries.
 */
function autoSlug(name: string): string {
  const ascii = name.toLowerCase()
    .trim()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
  const base = ascii || "skill";
  const tail = Math.random().toString(36).slice(2, 6);
  return `${base}-${tail}`;
}
