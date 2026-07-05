"use client";

/**
 * Skills v2 — Library (画面 1 from spec §3.1).
 *
 * Clean break from the legacy multi-step skill_documents Library. Lists
 * skills_v2 rows with role chips + trigger summary; click → Editor.
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { TK, FONT, ROLE_COLORS, ensurePlexFont } from "@/components/skills-v2/tokens";
import {
  parseTrigger, roleLabel, summarizeTrigger, type Role, type Skill,
} from "@/components/skills-v2/types";

type Filter = "all" | "patrol" | "datacheck" | "tool";

export default function SkillsLibraryPage() {
  const t = useTranslations("skills.library");
  const router = useRouter();
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [deletingSlug, setDeletingSlug] = useState<string | null>(null);

  useEffect(() => { ensurePlexFont(); }, []);

  const reload = () => {
    fetch("/api/skills-v2")
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(env => setSkills((env?.data ?? env) as Skill[]))
      .catch(e => setLoadError(e instanceof Error ? e.message : String(e)));
  };

  useEffect(() => { reload(); }, []);

  const handleDelete = async (skill: Skill) => {
    if (!confirm(t("confirmDelete", { name: skill.name }))) return;
    setDeletingSlug(skill.slug);
    try {
      const res = await fetch(`/api/skills-v2/${encodeURIComponent(skill.slug)}`, { method: "DELETE" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      // optimistic remove
      setSkills(prev => prev.filter(s => s.slug !== skill.slug));
    } catch (e) {
      alert(t("deleteFailed", { error: e instanceof Error ? e.message : String(e) }));
    } finally {
      setDeletingSlug(null);
    }
  };

  const counts = useMemo(() => ({
    all:       skills.length,
    patrol:    skills.filter(s => s.role === "patrol").length,
    datacheck: skills.filter(s => s.role === "datacheck").length,
    tool:      skills.filter(s => s.role === "tool").length,
  }), [skills]);

  const filtered = filter === "all" ? skills : skills.filter(s => s.role === filter);

  return (
    <div style={{ background: TK.page, minHeight: "100vh", padding: "32px 24px 80px", fontFamily: FONT.sans, color: TK.ink }}>
      <div style={{ maxWidth: 1000, margin: "0 auto" }}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 18 }}>
          <div>
            <div style={{
              font: `600 11px ${FONT.mono}`,
              letterSpacing: ".13em",
              color: TK.faint,
              textTransform: "uppercase",
              marginBottom: 6,
            }}>
              {t("eyebrow")}
            </div>
            <h1 style={{ font: `700 28px ${FONT.sans}`, color: TK.ink, margin: 0 }}>{t("title")}</h1>
            <p style={{ fontSize: 13, color: TK.body, margin: "6px 0 0", maxWidth: 720 }}>
              {t("intro")}
            </p>
          </div>
          <button
            onClick={() => router.push("/skills/new")}
            style={{
              font: `600 13px ${FONT.sans}`,
              color: "#fff", background: TK.black, border: `1px solid ${TK.black}`,
              padding: "10px 16px", borderRadius: 9, cursor: "pointer",
            }}
          >
            {t("newSkill")}
          </button>
        </div>

        {/* Filter chips */}
        <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
          <FilterChip label={t("filterAll")}       n={counts.all}       active={filter === "all"}       onClick={() => setFilter("all")} />
          <FilterChip label={t("filterPatrol")}    n={counts.patrol}    active={filter === "patrol"}    onClick={() => setFilter("patrol")} role="patrol" />
          <FilterChip label={t("filterDatacheck")} n={counts.datacheck} active={filter === "datacheck"} onClick={() => setFilter("datacheck")} role="datacheck" />
          <FilterChip label={t("filterTool")}      n={counts.tool}      active={filter === "tool"}      onClick={() => setFilter("tool")} role="tool" />
        </div>

        {/* List */}
        {loadError && (
          <div style={{ background: "#fef3f2", border: "1px solid #fecaca", color: "#b42318",
                         padding: 14, borderRadius: 8, fontSize: 13, marginBottom: 14 }}>
            {t("loadFailed", { error: loadError })}
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {filtered.map(s => (
            <SkillCard
              key={s.slug}
              skill={s}
              onDelete={() => handleDelete(s)}
              deleting={deletingSlug === s.slug}
            />
          ))}
          {filtered.length === 0 && !loadError && (
            <div style={{
              background: "#fff", border: `1px solid ${TK.divider}`, borderRadius: 10,
              padding: 32, textAlign: "center", color: TK.faint, fontSize: 13,
            }}>
              {t("emptyCategory")}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function DeleteButton({
  onDelete, deleting, skillName,
}: { onDelete: () => void; deleting: boolean; skillName: string }) {
  const t = useTranslations("skills.library");
  const [hover, setHover] = useState(false);
  return (
    <button
      onClick={onDelete}
      disabled={deleting}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      title={t("deleteTitle")}
      aria-label={t("deleteAria", { name: skillName })}
      style={{
        marginLeft: 4,
        width: 32, height: 32,
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        background: hover ? "#fef3f2" : "transparent",
        color: hover ? "#b42318" : "#94a3b8",
        border: `1px solid ${hover ? "#fecaca" : "transparent"}`,
        borderRadius: 7,
        cursor: deleting ? "wait" : "pointer",
        opacity: deleting ? 0.5 : 1,
        transition: "background 120ms, color 120ms, border 120ms",
        padding: 0,
      }}
    >
      {deleting ? (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
          <circle cx="12" cy="12" r="9" strokeOpacity=".3" />
          <path d="M21 12a9 9 0 0 0-9-9" />
        </svg>
      ) : (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 6h18" />
          <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
          <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
          <path d="M10 11v6M14 11v6" />
        </svg>
      )}
    </button>
  );
}

function FilterChip({
  label, n, active, onClick, role,
}: {
  label: string;
  n: number;
  active: boolean;
  onClick: () => void;
  role?: Role;
}) {
  const c = role ? ROLE_COLORS[role] : null;
  return (
    <button
      onClick={onClick}
      style={{
        font: `600 12.5px ${FONT.sans}`,
        background: active ? (c?.tint ?? TK.ink) : TK.card,
        color: active ? (c?.color ?? "#fff") : TK.body,
        border: `1px solid ${active ? (c?.border ?? TK.ink) : TK.divider}`,
        padding: "6px 12px",
        borderRadius: 7,
        cursor: "pointer",
      }}
    >
      {label} <span style={{ marginLeft: 4, opacity: .65 }}>{n}</span>
    </button>
  );
}

function SkillCard({ skill, onDelete, deleting }: { skill: Skill; onDelete: () => void; deleting: boolean }) {
  const t = useTranslations("skills.library");
  const c = ROLE_COLORS[skill.role];
  const trigger = parseTrigger(skill.trigger_config);
  const isActive = skill.status === "active";
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 16,
      background: TK.card, border: `1px solid ${TK.divider}`,
      borderRadius: 11, padding: "14px 18px",
    }}>
      {/* status dot — draft = hollow gray, active = filled role color */}
      <span
        title={isActive ? t("statusActive") : t("statusDraft")}
        style={{
          width: 9, height: 9, borderRadius: 5, flexShrink: 0,
          background: isActive ? c.color : "transparent",
          border: isActive ? "none" : `1.5px solid #cbd5e1`,
        }}
      />

      {/* main column */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ font: `600 15px ${FONT.sans}`, color: TK.ink, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {skill.name}
          </div>
          <span style={{
            font: `600 10.5px ${FONT.mono}`,
            color: c.color, background: c.tint, border: `1px solid ${c.border}`,
            padding: "3px 8px", borderRadius: 6, whiteSpace: "nowrap",
          }}>
            {roleLabel(skill.role)}
          </span>
          {!isActive && (
            <span style={{
              font: `600 10px ${FONT.mono}`,
              color: "#92400e", background: "#fffbeb", border: "1px solid #fde68a",
              padding: "3px 7px", borderRadius: 6, whiteSpace: "nowrap",
            }}>
              {t("draftBadge")}
            </span>
          )}
        </div>
        <div style={{ fontSize: 12.5, color: TK.body, marginTop: 4 }}>{skill.sub}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 8, fontSize: 11.5, color: TK.faint }}>
          <span style={{ fontFamily: FONT.mono }}>
            in: <span style={{ color: TK.body }}>{skill.in_type || "—"}</span>
            {" → "}
            out: <span style={{ color: TK.body }}>{skill.out_type || "—"}</span>
          </span>
          <span>·</span>
          <span style={{ fontFamily: FONT.mono }}>{summarizeTrigger(trigger)}</span>
        </div>
      </div>

      {/* actions */}
      <div style={{ display: "flex", gap: 8, flexShrink: 0, alignItems: "center" }}>
        <Link href={`/skills/${skill.id}`} style={{
          font: `600 12px ${FONT.sans}`,
          color: TK.ink, background: TK.card,
          border: `1px solid ${TK.divider}`, padding: "7px 13px", borderRadius: 8,
          textDecoration: "none",
        }}>{t("edit")}</Link>
        <Link href={`/skills/${skill.id}/automate`} style={{
          font: `600 12px ${FONT.sans}`,
          color: skill.role === "tool" ? "#fff" : TK.ink,
          background: skill.role === "tool" ? TK.black : TK.card,
          border: `1px solid ${skill.role === "tool" ? TK.black : TK.divider}`,
          padding: "7px 13px", borderRadius: 8, textDecoration: "none",
        }}>
          {skill.role === "tool" ? t("setupAutomation") : t("editAutomation")}
        </Link>
        <DeleteButton onDelete={onDelete} deleting={deleting} skillName={skill.name} />
      </div>
    </div>
  );
}
