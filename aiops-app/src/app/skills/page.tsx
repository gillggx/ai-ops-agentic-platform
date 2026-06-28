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
import { TK, FONT, ROLE_COLORS, ensurePlexFont } from "@/components/skills-v2/tokens";
import {
  parseTrigger, roleLabel, summarizeTrigger, type Role, type Skill,
} from "@/components/skills-v2/types";

type Filter = "all" | "patrol" | "datacheck" | "tool";

export default function SkillsLibraryPage() {
  const router = useRouter();
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");

  useEffect(() => { ensurePlexFont(); }, []);

  useEffect(() => {
    fetch("/api/skills-v2")
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(env => setSkills((env?.data ?? env) as Skill[]))
      .catch(e => setLoadError(e instanceof Error ? e.message : String(e)));
  }, []);

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
              SKILLS LIBRARY
            </div>
            <h1 style={{ font: `700 28px ${FONT.sans}`, color: TK.ink, margin: 0 }}>Skills</h1>
            <p style={{ fontSize: 13, color: TK.body, margin: "6px 0 0", maxWidth: 720 }}>
              用自然語言描述、編譯成 data pipeline 的可重用工具。Skill 建好後可選擇自動化成 Auto Patrol 或 Data Check，或先當純工具用。
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
            + 新增 Skill
          </button>
        </div>

        {/* Filter chips */}
        <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
          <FilterChip label="全部"        n={counts.all}       active={filter === "all"}       onClick={() => setFilter("all")} />
          <FilterChip label="Auto Patrol" n={counts.patrol}    active={filter === "patrol"}    onClick={() => setFilter("patrol")} role="patrol" />
          <FilterChip label="Data Check"  n={counts.datacheck} active={filter === "datacheck"} onClick={() => setFilter("datacheck")} role="datacheck" />
          <FilterChip label="工具"        n={counts.tool}      active={filter === "tool"}      onClick={() => setFilter("tool")} role="tool" />
        </div>

        {/* List */}
        {loadError && (
          <div style={{ background: "#fef3f2", border: "1px solid #fecaca", color: "#b42318",
                         padding: 14, borderRadius: 8, fontSize: 13, marginBottom: 14 }}>
            載入失敗：{loadError}
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {filtered.map(s => <SkillCard key={s.slug} skill={s} />)}
          {filtered.length === 0 && !loadError && (
            <div style={{
              background: "#fff", border: `1px solid ${TK.divider}`, borderRadius: 10,
              padding: 32, textAlign: "center", color: TK.faint, fontSize: 13,
            }}>
              這個分類下沒有 skill。
            </div>
          )}
        </div>
      </div>
    </div>
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

function SkillCard({ skill }: { skill: Skill }) {
  const c = ROLE_COLORS[skill.role];
  const trigger = parseTrigger(skill.trigger_config);
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 16,
      background: TK.card, border: `1px solid ${TK.divider}`,
      borderRadius: 11, padding: "14px 18px",
    }}>
      {/* dot */}
      <span style={{
        width: 9, height: 9, borderRadius: 5,
        background: c.color, flexShrink: 0,
      }} />

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
      <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
        <Link href={`/skills/${encodeURIComponent(skill.slug)}`} style={{
          font: `600 12px ${FONT.sans}`,
          color: TK.ink, background: TK.card,
          border: `1px solid ${TK.divider}`, padding: "7px 13px", borderRadius: 8,
          textDecoration: "none",
        }}>編寫</Link>
        <Link href={`/skills/${encodeURIComponent(skill.slug)}/automate`} style={{
          font: `600 12px ${FONT.sans}`,
          color: skill.role === "tool" ? "#fff" : TK.ink,
          background: skill.role === "tool" ? TK.black : TK.card,
          border: `1px solid ${skill.role === "tool" ? TK.black : TK.divider}`,
          padding: "7px 13px", borderRadius: 8, textDecoration: "none",
        }}>
          {skill.role === "tool" ? "設定自動化" : "編輯自動化"}
        </Link>
      </div>
    </div>
  );
}
