"use client";

/**
 * Skills v2 — Editor (画面 2 from spec §3.2).
 *
 * Two-column NL → pipeline. Compile button triggers ~750ms shimmer then
 * paints right-column rule list. System alarm check banner says whether
 * the pipeline contains a verdict node (→ Auto Patrol eligible).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { TK, FONT, ROLE_COLORS, ensurePlexFont } from "@/components/skills-v2/tokens";
import { parsePipelineNodes, roleLabel, type Skill, type PipelineNode } from "@/components/skills-v2/types";
import { writeSkillV2Ctx } from "@/components/skills-v2/SkillV2EmbedBanner";
import SkillCanvasView from "@/components/skills-v2/SkillCanvasView";
import SkillTryRunPanel from "@/components/skills-v2/SkillTryRunPanel";

export default function SkillEditorPage() {
  const t = useTranslations("skills.editor");
  const params = useParams<{ slug: string }>();
  const router = useRouter();
  const slug = params?.slug ?? "";

  const [skill, setSkill] = useState<Skill | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [nl, setNl] = useState("");
  const [nlDirty, setNlDirty] = useState(false);
  const [pipeline, setPipeline] = useState<PipelineNode[]>([]);
  const [hasAlarm, setHasAlarm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [opening, setOpening] = useState(false);
  const [activating, setActivating] = useState(false);
  const [toast, setToast] = useState("");
  const nlRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => { ensurePlexFont(); }, []);

  // Auto-grow the NL textarea to fit content (wrapped lines included, not just \n count).
  useEffect(() => {
    const el = nlRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 360)}px`;
  }, [nl]);

  useEffect(() => {
    if (!slug) return;
    fetch(`/api/skills-v2/${encodeURIComponent(slug)}`)
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(env => {
        const s = (env?.data ?? env) as Skill;
        setSkill(s);
        setNl(s.nl);
        setPipeline(parsePipelineNodes(s.pipeline_nodes));
        setHasAlarm(s.has_alarm);
      })
      .catch(e => setLoadError(e instanceof Error ? e.message : String(e)));
  }, [slug]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 2400);
    return () => clearTimeout(t);
  }, [toast]);

  /**
   * "重新編譯 ↻" no longer calls a synchronous mock — it opens Pipeline
   * Builder in {@code embed=skill-v2} mode. PB's agent panel builds the
   * pipeline; SkillV2EmbedBanner auto-binds the resulting pb_pipeline
   * back to this skill_v2 row (pipeline_id + pipeline_nodes derived
   * server-side). User returns to this Editor and sees the new pipeline.
   */
  const handleOpenBuilder = useCallback(async (mode: "compile" | "rebuild" | "edit") => {
    if (!skill) return;
    setOpening(true);
    try {
      // Persist NL first so the round-trip doesn't lose unsaved edits.
      if (nlDirty) {
        await fetch(`/api/skills-v2/${encodeURIComponent(slug)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ nl }),
        });
      }
      writeSkillV2Ctx({ skill_slug: slug, name: skill.name, nl, mode });
      // edit → load existing pipeline (no agent); compile/rebuild → /new triggers agent auto-fire
      const target = (mode === "edit" && skill.pipeline_id)
        ? `/admin/pipeline-builder/${skill.pipeline_id}?embed=skill-v2&slug=${encodeURIComponent(slug)}&mode=edit`
        : `/admin/pipeline-builder/new?embed=skill-v2&slug=${encodeURIComponent(slug)}&mode=${mode}`;
      router.push(target);
    } catch (e) {
      setToast(t("openBuilderFailed", { error: e instanceof Error ? e.message : String(e) }));
      setOpening(false);
    }
  }, [nl, nlDirty, skill, slug, router, t]);

  const handleSaveNl = useCallback(async () => {
    if (!skill) return;
    setSaving(true);
    try {
      const res = await fetch(`/api/skills-v2/${encodeURIComponent(slug)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nl }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const env = await res.json();
      setSkill((env?.data ?? env) as Skill);
      setNlDirty(false);
      setToast(t("saved"));
    } catch (e) {
      setToast(t("saveFailed", { error: e instanceof Error ? e.message : String(e) }));
    } finally {
      setSaving(false);
    }
  }, [nl, skill, slug, t]);

  const handleToggleActive = useCallback(async (activate: boolean) => {
    if (!skill) return;
    setActivating(true);
    try {
      const res = await fetch(`/api/skills-v2/${encodeURIComponent(slug)}/activate`, {
        method: activate ? "POST" : "DELETE",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const env = await res.json();
      setSkill((env?.data ?? env) as Skill);
      setToast(activate ? t("activatedToast") : t("deactivatedToast"));
    } catch (e) {
      setToast(t("actionFailed", { error: e instanceof Error ? e.message : String(e) }));
    } finally {
      setActivating(false);
    }
  }, [skill, slug, t]);

  if (loadError) return <Center>{t("loadFailed", { error: loadError })}</Center>;
  if (!skill) return <Center>{t("loading")}</Center>;

  const c = ROLE_COLORS[skill.role];

  return (
    <div style={{ background: TK.page, minHeight: "100vh", padding: "24px 24px 80px", fontFamily: FONT.sans, color: TK.ink }}>
      <div style={{ maxWidth: 1080, margin: "0 auto" }}>
        {/* Back */}
        <div style={{ marginBottom: 12 }}>
          <Link href="/skills" style={{
            color: TK.body, fontSize: 13, textDecoration: "none",
          }}>{t("backToLibrary")}</Link>
        </div>

        {/* Header */}
        <div style={{
          background: TK.card, borderRadius: 14, padding: "18px 22px",
          boxShadow: "0 1px 3px rgba(15,18,30,.06)",
          marginBottom: 14,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <div style={{ font: `600 11px ${FONT.mono}`, color: TK.faint, letterSpacing: ".13em", textTransform: "uppercase" }}>
              {t("eyebrow")}
            </div>
            <span style={{
              font: `600 10.5px ${FONT.mono}`,
              color: TK.indigo, background: TK.indigoTint,
              padding: "3px 8px", borderRadius: 6,
            }}>{t("mcpChip")}</span>
            <span style={{
              font: `600 10.5px ${FONT.mono}`,
              color: c.color, background: c.tint, border: `1px solid ${c.border}`,
              padding: "3px 8px", borderRadius: 6,
            }}>{roleLabel(skill.role)}</span>
          </div>
          <h1 style={{ font: `700 22px ${FONT.sans}`, color: TK.ink, margin: "8px 0 4px" }}>{skill.name}</h1>
          <div style={{ fontSize: 13, color: TK.body }}>{skill.sub}</div>
        </div>

        {/* Stacked: NL on top (full width) → pipeline canvas below */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* NL description */}
          <Column>
            <ColumnHeader>{t("nlHeader")}</ColumnHeader>
            <textarea
              ref={nlRef}
              value={nl}
              onChange={(e) => { setNl(e.target.value); setNlDirty(true); }}
              placeholder={t("nlPlaceholder")}
              style={{
                minHeight: 56, overflowY: "auto",
                padding: "12px 18px", border: "none", outline: "none",
                resize: "none",
                font: `15px/1.6 ${FONT.sans}`, color: TK.ink, background: "#fff",
              }}
            />
            <ColumnFooter>
              <span style={{ fontSize: 11, color: TK.faint }}>
                {nlDirty ? t("unsaved") : t("saved")}
              </span>
              <div style={{ display: "flex", gap: 8 }}>
                <button onClick={handleSaveNl} disabled={!nlDirty || saving} style={{
                  font: `600 12px ${FONT.sans}`,
                  color: TK.ink, background: "#fff",
                  border: `1px solid ${TK.divider}`,
                  padding: "7px 12px", borderRadius: 8,
                  cursor: nlDirty ? "pointer" : "not-allowed",
                  opacity: nlDirty ? 1 : 0.5,
                }}>
                  {saving ? t("saving") : t("saveDraft")}
                </button>
              </div>
            </ColumnFooter>
          </Column>

          {/* Pipeline canvas (read-only, real DagCanvas like chat-mode lite canvas) */}
          <Column>
            <div style={{
              padding: "10px 18px", borderBottom: `1px solid ${TK.divider}`,
              display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
            }}>
              <span style={{
                font: `600 11px ${FONT.mono}`, letterSpacing: ".13em",
                color: TK.body, textTransform: "uppercase",
              }}>
                {t("compiledHeader")}
                <span style={{ color: TK.faint, marginLeft: 10 }}>{t("nodeCount", { n: pipeline.length })}</span>
              </span>
              <span style={{ display: "flex", gap: 8 }}>
                {skill.pipeline_id ? (
                  <>
                    <button onClick={() => handleOpenBuilder("rebuild")} disabled={opening} title={t("rebuildTitle")} style={{
                      font: `600 11.5px ${FONT.sans}`,
                      color: TK.body, background: "#fff",
                      border: `1px solid ${TK.divider}`,
                      padding: "6px 11px", borderRadius: 7, cursor: "pointer",
                    }}>
                      {t("rebuild")}
                    </button>
                    <button onClick={() => handleOpenBuilder("edit")} disabled={opening} title={t("editPipelineTitle")} style={{
                      font: `600 11.5px ${FONT.sans}`,
                      color: "#fff", background: TK.indigo, border: `1px solid ${TK.indigo}`,
                      padding: "6px 11px", borderRadius: 7, cursor: "pointer",
                    }}>
                      {opening ? t("opening") : t("editPipeline")}
                    </button>
                  </>
                ) : (
                  <button onClick={() => handleOpenBuilder("compile")} disabled={opening} style={{
                    font: `600 11.5px ${FONT.sans}`,
                    color: "#fff", background: TK.indigo, border: `1px solid ${TK.indigo}`,
                    padding: "6px 11px", borderRadius: 7, cursor: "pointer",
                  }}>
                    {opening ? t("opening") : t("compileWithBuilder")}
                  </button>
                )}
              </span>
            </div>
            <div style={{ padding: "14px 18px" }}>
              <SkillCanvasView pipelineId={skill.pipeline_id} height={460} />
            </div>
          </Column>

          {/* Try Run — read-only dry-run of the bound pipeline */}
          {skill.pipeline_id != null && (
            <SkillTryRunPanel pipelineId={skill.pipeline_id} />
          )}
        </div>

        {/* System alarm check */}
        <AlarmCheck hasAlarm={hasAlarm} />

        {/* Activation gate — only meaningful once a pipeline is bound */}
        {skill.pipeline_id != null && (
          <ActivationBanner
            status={skill.status}
            busy={activating}
            onActivate={() => handleToggleActive(true)}
            onDeactivate={() => handleToggleActive(false)}
          />
        )}

        {/* Contract + action */}
        <ContractStrip
          inType={skill.in_type}
          outType={skill.out_type}
          actionLabel={skill.role === "tool" ? t("automateAction") : t("editAutomationAction")}
          onAction={() => router.push(`/skills/${encodeURIComponent(slug)}/automate`)}
        />
      </div>

      {toast && <Toast text={toast} />}

      <style>{`
        @media (max-width: 800px) {
          .editor-cols { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  );
}

function Column({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      background: TK.card, borderRadius: 14,
      boxShadow: "0 1px 3px rgba(15,18,30,.06)",
      display: "flex", flexDirection: "column", overflow: "hidden",
    }}>{children}</div>
  );
}

function ColumnHeader({ children, rightChip }: { children: React.ReactNode; rightChip?: string }) {
  return (
    <div style={{
      padding: "12px 18px", borderBottom: `1px solid ${TK.divider}`,
      display: "flex", justifyContent: "space-between", alignItems: "center",
      font: `600 11px ${FONT.mono}`,
      letterSpacing: ".13em",
      color: TK.body,
      textTransform: "uppercase",
    }}>
      <span>{children}</span>
      {rightChip && <span style={{ color: TK.faint }}>{rightChip}</span>}
    </div>
  );
}

function ColumnFooter({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      padding: "10px 18px", borderTop: `1px solid ${TK.divider}`,
      background: "#fbfbfc",
      display: "flex", justifyContent: "space-between", alignItems: "center",
    }}>{children}</div>
  );
}

function ActivationBanner({
  status, busy, onActivate, onDeactivate,
}: {
  status: string; busy: boolean; onActivate: () => void; onDeactivate: () => void;
}) {
  const t = useTranslations("skills.editor");
  const active = status === "active";
  return (
    <div style={{
      marginTop: 14,
      background: active ? "#f0fdf4" : "#fffbeb",
      border: `1px solid ${active ? "#bbf7d0" : "#fde68a"}`,
      borderRadius: 10, padding: "12px 18px",
      display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16,
    }}>
      <div style={{ font: `500 12.5px ${FONT.sans}`, color: active ? "#166534" : "#92400e" }}>
        {active ? t("activeBanner") : t("draftBanner")}
      </div>
      {active ? (
        <button onClick={onDeactivate} disabled={busy} style={{
          font: `600 12px ${FONT.sans}`,
          color: "#92400e", background: "#fff", border: "1px solid #fde68a",
          padding: "7px 14px", borderRadius: 8, cursor: busy ? "wait" : "pointer",
          opacity: busy ? 0.6 : 1, whiteSpace: "nowrap",
        }}>
          {busy ? "…" : t("deactivate")}
        </button>
      ) : (
        <button onClick={onActivate} disabled={busy} style={{
          font: `700 12.5px ${FONT.sans}`,
          color: "#fff", background: "#16a34a", border: "1px solid #16a34a",
          padding: "8px 18px", borderRadius: 8, cursor: busy ? "wait" : "pointer",
          opacity: busy ? 0.6 : 1, whiteSpace: "nowrap",
        }}>
          {busy ? t("activating") : t("activate")}
        </button>
      )}
    </div>
  );
}

function AlarmCheck({ hasAlarm }: { hasAlarm: boolean }) {
  const t = useTranslations("skills.editor");
  if (hasAlarm) {
    return (
      <div style={{
        marginTop: 14,
        background: TK.patrolTint, border: `1px solid ${TK.patrolBorder}`,
        borderRadius: 10, padding: "11px 16px",
        font: `500 12.5px ${FONT.sans}`, color: TK.patrolDeep,
      }}>
        {t("alarmYes")}
      </div>
    );
  }
  return (
    <div style={{
      marginTop: 14,
      background: TK.toolTint, border: `1px solid ${TK.toolBorder}`,
      borderRadius: 10, padding: "11px 16px",
      font: `500 12.5px ${FONT.sans}`, color: TK.body,
    }}>
      {t("alarmNo")}
    </div>
  );
}

function ContractStrip({
  inType, outType, actionLabel, onAction,
}: {
  inType: string; outType: string; actionLabel: string; onAction: () => void;
}) {
  return (
    <div style={{
      marginTop: 14,
      padding: "12px 18px", borderRadius: 10,
      background: "#fbfbfc", border: `1px solid ${TK.divider}`,
      display: "flex", alignItems: "center", justifyContent: "space-between",
      font: `13px ${FONT.mono}`,
    }}>
      <span style={{ color: TK.body }}>
        <strong style={{ color: TK.ink }}>in:</strong> {inType || "—"}
        <span style={{ margin: "0 10px", color: TK.faint }}>→</span>
        <strong style={{ color: TK.ink }}>out:</strong> {outType || "—"}
      </span>
      <button onClick={onAction} style={{
        font: `600 13px ${FONT.sans}`,
        color: "#fff", background: TK.black, border: `1px solid ${TK.black}`,
        padding: "8px 14px", borderRadius: 8, cursor: "pointer",
      }}>{actionLabel}</button>
    </div>
  );
}

function Center({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ background: TK.page, minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: FONT.sans }}>
      <div style={{ background: "#fff", padding: "24px 30px", borderRadius: 12, color: TK.body }}>{children}</div>
    </div>
  );
}

function Toast({ text }: { text: string }) {
  return (
    <div style={{
      position: "fixed", bottom: 28, left: "50%", transform: "translateX(-50%)",
      background: TK.black, color: "#fff",
      padding: "9px 16px", borderRadius: 9,
      fontSize: 13, boxShadow: "0 8px 24px rgba(0,0,0,.25)",
      zIndex: 60, maxWidth: 480,
      fontFamily: FONT.sans,
    }}>{text}</div>
  );
}
