"use client";

/**
 * Skills Library — port of prototype `Skills Library.html` + `library.jsx`.
 * Shape and styling kept faithful: TopBar, Hero stats, FilterBar (tabs +
 * search), StageSection (Patrol / Diagnose), SkillRow.
 *
 * Talks to /api/skill-documents for the list.
 */
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Icon, Stat, StagePill, StatusDot, TriggerChip, Sparkline,
  STAGES, safeParse,
  type SkillSummary, type TriggerConfig, type SkillStats,
} from "./atoms";

interface ApiList { ok: boolean; data: SkillSummary[]; error?: { message: string } | null }

export default function Library() {
  const [filter, setFilter] = useState<"all" | "patrol" | "diagnose">("all");
  const [query, setQuery] = useState("");
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch("/api/skill-documents", { cache: "no-store" })
      .then(async (res) => {
        const json = (await res.json()) as ApiList;
        if (cancelled) return;
        if (!res.ok || !json.ok) throw new Error(json.error?.message || `HTTP ${res.status}`);
        setSkills(json.data || []);
      })
      .catch((e: Error) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const filtered = useMemo(() => {
    let list = skills;
    if (filter !== "all") list = list.filter((s) => s.stage === filter);
    if (query.trim()) {
      const q = query.toLowerCase();
      list = list.filter((s) =>
        s.title.toLowerCase().includes(q) ||
        s.description.toLowerCase().includes(q) ||
        s.domain.toLowerCase().includes(q),
      );
    }
    return list;
  }, [skills, filter, query]);

  const grouped = useMemo(() => {
    const g: Record<"patrol" | "diagnose", SkillSummary[]> = { patrol: [], diagnose: [] };
    filtered.forEach((s) => g[s.stage].push(s));
    return g;
  }, [filtered]);

  const totalRunsLast30d = useMemo(() => {
    return skills.reduce((sum, s) => {
      const stats = safeParse<SkillStats>(s.stats, {});
      return sum + (stats.runs_30d ?? 0);
    }, 0);
  }, [skills]);

  const certifiedCount = skills.filter((s) => s.certified_by).length;
  const ratingAvg = useMemo(() => {
    const r = skills
      .map((s) => safeParse<SkillStats>(s.stats, {}).rating_avg)
      .filter((v): v is number => typeof v === "number");
    if (!r.length) return null;
    return Math.round((r.reduce((a, b) => a + b, 0) / r.length) * 10) / 10;
  }, [skills]);

  return (
    <div className="skill-surface">
      <TopBar />
      <main style={{ maxWidth: 1240, margin: "0 auto", padding: "0 32px 80px" }}>
        <Hero
          totalSkills={skills.length}
          runs30d={totalRunsLast30d}
          certifiedCount={certifiedCount}
          activeTriggers={skills.filter((s) => s.status === "stable").length}
          ratingAvg={ratingAvg}
        />
        <FilterBar
          filter={filter} setFilter={setFilter}
          query={query} setQuery={setQuery}
          results={filtered.length}
        />

        {error && (
          <div style={{ marginTop: 24, padding: "14px 18px", background: "var(--fail-bg)",
                        border: "1px solid var(--fail)", borderRadius: 10,
                        color: "var(--fail)", fontSize: 13 }}>
            載入失敗：{error}
          </div>
        )}

        {loading ? (
          <div style={{ marginTop: 60, textAlign: "center", color: "var(--ink-3)", fontSize: 13 }}>
            <span className="skill-spinner" style={{ marginRight: 8 }}/> 載入 skills…
          </div>
        ) : (
          <>
            {filter === "all" ? (
              (["patrol", "diagnose"] as const).map((stage) =>
                grouped[stage].length > 0 ? (
                  <StageSection key={stage} stage={stage} count={grouped[stage].length}>
                    {grouped[stage].map((s) => <SkillRow key={s.id} skill={s}/>)}
                  </StageSection>
                ) : null,
              )
            ) : (
              <div style={{ marginTop: 8 }}>
                {filtered.map((s) => <SkillRow key={s.id} skill={s}/>)}
              </div>
            )}

            {filtered.length === 0 && (
              <div style={{
                marginTop: 60, padding: "40px 20px", textAlign: "center",
                border: "1px dashed var(--line-strong)", borderRadius: 10,
                color: "var(--ink-3)",
              }}>
                <div style={{ fontSize: 14, color: "var(--ink-2)", fontWeight: 500, marginBottom: 6 }}>
                  {skills.length === 0 ? "目前沒有任何 skill" : "沒有符合的 skill"}
                </div>
                <div style={{ fontSize: 12.5 }}>
                  {skills.length === 0 ? "建立第一個 skill 文件，把工程師領域知識變成可審查、可執行的資產。" : "嘗試清除篩選條件。"}
                </div>
              </div>
            )}

            {/* Footer hint about authoring */}
            <div style={{
              marginTop: 60, padding: "20px 22px",
              background: "var(--sys-bg)", border: "1px solid var(--sys-line)", borderRadius: 12,
              display: "flex", alignItems: "center", gap: 18,
            }}>
              <span style={{
                width: 36, height: 36, borderRadius: 8, flexShrink: 0,
                display: "inline-flex", alignItems: "center", justifyContent: "center",
                background: "var(--ai-bg)", color: "var(--ai)",
              }}>
                <Icon.Spark/>
              </span>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13.5, fontWeight: 600, marginBottom: 2 }}>用自然語言寫一份新的 Skill</div>
                <div style={{ fontSize: 12.5, color: "var(--ink-3)", lineHeight: 1.55 }}>
                  描述每個檢查步驟，AI 會自動翻譯成 data pipeline，您只需審閱並 confirm。
                </div>
              </div>
              <Link href="/skills/new" style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "8px 14px", borderRadius: 6,
                background: "var(--accent)", color: "var(--bg)",
                fontSize: 12.5, fontWeight: 500,
              }}>
                <Icon.Plus/> Author a new skill
              </Link>
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function TopBar() {
  return (
    <div style={{
      position: "sticky", top: 0, zIndex: 20,
      background: "var(--bg)", borderBottom: "1px solid var(--line)",
      padding: "10px 32px", display: "flex", alignItems: "center", gap: 16,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{
          width: 22, height: 22, borderRadius: 6, background: "var(--accent)",
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          color: "var(--bg)",
        }}>
          <Icon.Spark/>
        </span>
        <span style={{ fontSize: 13.5, fontWeight: 600 }}>AIOps Skills</span>
      </div>
      <div style={{ width: 1, height: 18, background: "var(--line)", margin: "0 4px" }}/>
      <Link href="/skills" style={{ fontSize: 12.5, fontWeight: 500, color: "var(--ink)" }}>Library</Link>
      <span style={{ flex: 1 }}/>
      <Link href="/skills/new" style={{
        display: "inline-flex", alignItems: "center", gap: 6,
        padding: "6px 11px", borderRadius: 6,
        background: "var(--accent)", color: "var(--bg)",
        border: "1px solid var(--accent)",
        fontSize: 12.5, fontWeight: 500, cursor: "pointer",
      }}>
        <Icon.Plus/> New Skill
      </Link>
    </div>
  );
}

function Hero({
  totalSkills, runs30d, certifiedCount, activeTriggers, ratingAvg,
}: {
  totalSkills: number; runs30d: number; certifiedCount: number; activeTriggers: number; ratingAvg: number | null;
}) {
  return (
    <div style={{ padding: "44px 0 24px" }}>
      <div className="mono" style={{ fontSize: 11, letterSpacing: "0.08em", color: "var(--ink-3)", marginBottom: 12 }}>
        SKILLS LIBRARY · KNOWLEDGE ASSETS
      </div>
      <h1 style={{ margin: 0, fontSize: 34, fontWeight: 600, letterSpacing: "-0.018em", lineHeight: 1.1 }}>
        Senior engineering knowledge,<br/>codified as executable skills.
      </h1>
      <p style={{ marginTop: 14, marginBottom: 0, fontSize: 14.5, color: "var(--ink-2)", maxWidth: 640, lineHeight: 1.6, textWrap: "pretty" }}>
        每個 skill 都是一份可被審查、被執行、被交易的工程文件。
        從 patrol 持續監看到 diagnose 根因分析的完整鏈路。
      </p>

      <div style={{
        marginTop: 28, padding: "20px 22px",
        background: "var(--sys-bg)", border: "1px solid var(--sys-line)", borderRadius: 12,
        display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 28,
      }}>
        <Stat label="TOTAL SKILLS"     value={String(totalSkills)} sub={`across ${(["patrol", "diagnose"] as const).filter(() => true).length} stages`}/>
        <Stat label="EXECUTIONS · 30D" value={runs30d.toLocaleString()} sub="last 30 days" />
        <Stat label="CERTIFIED"        value={String(certifiedCount)} sub="by domain owners"/>
        <Stat label="ACTIVE TRIGGERS"  value={String(activeTriggers)} sub="status=stable"/>
        <Stat label="AVG. RATING"
              value={ratingAvg != null
                ? <><span>{ratingAvg.toFixed(1)}</span><span style={{ fontSize: 14, color: "var(--ink-3)", fontWeight: 400 }}> / 5</span></>
                : "—"}/>
      </div>
    </div>
  );
}

function FilterBar({
  filter, setFilter, query, setQuery, results,
}: {
  filter: "all" | "patrol" | "diagnose";
  setFilter: (v: "all" | "patrol" | "diagnose") => void;
  query: string;
  setQuery: (v: string) => void;
  results: number;
}) {
  const tabs = [
    { id: "all" as const, label: "All" },
    { id: "patrol" as const, label: "Patrol" },
    { id: "diagnose" as const, label: "Diagnose" },
  ];
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12,
      padding: "14px 0",
      borderTop: "1px solid var(--line)",
      borderBottom: "1px solid var(--line)",
      position: "sticky", top: 50, background: "var(--bg)", zIndex: 5,
    }}>
      <div style={{ display: "inline-flex", padding: 2, borderRadius: 8, background: "var(--surface-2)", border: "1px solid var(--line)" }}>
        {tabs.map((t) => (
          <button key={t.id} onClick={() => setFilter(t.id)} style={{
            padding: "5px 12px", borderRadius: 6, border: "none",
            background: filter === t.id ? "var(--surface)" : "transparent",
            color: filter === t.id ? "var(--ink)" : "var(--ink-3)",
            fontSize: 12, fontWeight: 500, cursor: "pointer",
            boxShadow: filter === t.id ? "0 1px 2px rgba(0,0,0,0.06)" : "none",
          }}>{t.label}</button>
        ))}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5, color: "var(--ink-3)" }}>
        <Icon.Filter/>
        <span className="mono">domain: any</span>
        <span style={{ color: "var(--ink-4)" }}>·</span>
        <span className="mono">status: any</span>
      </div>
      <div style={{ flex: 1 }}/>
      <span style={{ fontSize: 11.5, color: "var(--ink-3)" }}>{results} results</span>
      <div style={{
        display: "flex", alignItems: "center", gap: 6,
        padding: "5px 10px", borderRadius: 6,
        background: "var(--surface-2)", border: "1px solid var(--line)",
        width: 240,
      }}>
        <Icon.Search/>
        <input value={query} onChange={(e) => setQuery(e.target.value)}
          placeholder="搜尋 skill / domain / author…"
          style={{ flex: 1, fontSize: 12.5, border: "none", background: "transparent", outline: "none", fontFamily: "inherit", color: "var(--ink)" }}/>
        <span className="mono" style={{ fontSize: 10, color: "var(--ink-4)" }}>⌘K</span>
      </div>
    </div>
  );
}

function StageSection({
  stage, count, children,
}: { stage: "patrol" | "diagnose"; count: number; children: React.ReactNode }) {
  const s = STAGES[stage];
  return (
    <section style={{ marginTop: 28 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 14, padding: "0 0 8px" }}>
        <span style={{ width: 7, height: 7, borderRadius: 999, background: s.dot }}/>
        <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, letterSpacing: "-0.01em" }}>{s.label}</h2>
        <span className="mono" style={{ fontSize: 11, color: "var(--ink-3)" }}>{count} skill{count > 1 ? "s" : ""}</span>
        <span style={{ fontSize: 12, color: "var(--ink-3)", marginLeft: 4 }}>· {s.desc}</span>
      </div>
      <div>{children}</div>
    </section>
  );
}

function SkillRow({ skill }: { skill: SkillSummary }) {
  const trig = safeParse<TriggerConfig>(skill.trigger_config, {});
  const stats = safeParse<SkillStats>(skill.stats, {});
  const trigKind: "system" | "user" | "schedule" = trig.type ?? "schedule";
  const trigLabel = trig.type === "system"
    ? trig.event_type ?? "?"
    : trig.type === "user"
    ? trig.name ?? "(custom)"
    : trig.cron ?? "—";

  return (
    <Link href={`/skills/${encodeURIComponent(skill.slug)}`}
      style={{
        display: "grid",
        gridTemplateColumns: "auto 1fr auto auto auto auto",
        alignItems: "center", gap: 24,
        padding: "20px 8px",
        borderBottom: "1px solid var(--line)",
        transition: "background 120ms",
        cursor: "pointer",
      }}>
      <div style={{ width: 14, display: "flex", justifyContent: "center" }}>
        <span style={{ width: 6, height: 6, borderRadius: 999, background: STAGES[skill.stage].dot, marginTop: 2 }}/>
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span style={{ fontSize: 15, fontWeight: 550, color: "var(--ink)", letterSpacing: "-0.005em" }}>
            {skill.title}
          </span>
          <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-3)", padding: "1px 6px", border: "1px solid var(--line)", borderRadius: 4 }}>
            v{skill.version}
          </span>
          {skill.certified_by && (
            <span style={{
              display: "inline-flex", alignItems: "center", gap: 4,
              fontSize: 10.5, color: "var(--pass)",
              padding: "2px 7px", background: "var(--pass-bg)", borderRadius: 4,
            }}>
              <Icon.Check/> {skill.certified_by}
            </span>
          )}
        </div>
        <div style={{ marginTop: 5, fontSize: 12.5, color: "var(--ink-3)", lineHeight: 1.5, maxWidth: 640, textWrap: "pretty" }}>
          {skill.description || <span style={{ color: "var(--ink-4)" }}>(no description)</span>}
        </div>
        <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <StagePill stage={skill.stage}/>
          <TriggerChip kind={trigKind} label={trigLabel}/>
          <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-3)" }}>
            {skill.domain || "—"}
          </span>
        </div>
      </div>
      <div style={{ textAlign: "right", minWidth: 60 }}>
        <div className="mono" style={{ fontSize: 9.5, letterSpacing: "0.08em", color: "var(--ink-3)", marginBottom: 4 }}>RATING</div>
        <div style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 13, fontWeight: 500 }}>
          <Icon.Star color="#d4a017"/>{stats.rating_avg ?? "—"}
        </div>
      </div>
      <div style={{ textAlign: "right", minWidth: 80 }}>
        <div className="mono" style={{ fontSize: 9.5, letterSpacing: "0.08em", color: "var(--ink-3)", marginBottom: 4 }}>RUNS · 30D</div>
        <Sparkline value={stats.runs_30d ?? 0}/>
      </div>
      <div style={{ textAlign: "right", minWidth: 110 }}>
        <div className="mono" style={{ fontSize: 9.5, letterSpacing: "0.08em", color: "var(--ink-3)", marginBottom: 4 }}>UPDATED</div>
        <div style={{ fontSize: 12, color: "var(--ink-2)" }}>
          {skill.updated_at ? new Date(skill.updated_at).toLocaleDateString() : "—"}
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <StatusDot status={skill.status}/>
        <span style={{
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          width: 26, height: 26, borderRadius: 6,
          background: "var(--surface-2)",
          color: "var(--ink-3)",
          border: "1px solid var(--line)",
        }}>
          <Icon.Arrow/>
        </span>
      </div>
    </Link>
  );
}
