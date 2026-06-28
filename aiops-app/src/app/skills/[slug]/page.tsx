"use client";

/**
 * Skills v2 — Editor (画面 2 from spec §3.2).
 *
 * Two-column NL → pipeline. Compile button triggers ~750ms shimmer then
 * paints right-column rule list. System alarm check banner says whether
 * the pipeline contains a verdict node (→ Auto Patrol eligible).
 */

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { TK, FONT, ROLE_COLORS, ensurePlexFont } from "@/components/skills-v2/tokens";
import { parsePipelineNodes, roleLabel, type Skill, type PipelineNode } from "@/components/skills-v2/types";
import { writeSkillV2Ctx } from "@/components/skills-v2/SkillV2EmbedBanner";
import PipelineSvgThumb from "@/components/skills-v2/PipelineSvgThumb";

export default function SkillEditorPage() {
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

  useEffect(() => { ensurePlexFont(); }, []);

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
      setToast(`開啟 Builder 失敗：${e instanceof Error ? e.message : e}`);
      setOpening(false);
    }
  }, [nl, nlDirty, skill, slug, router]);

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
      setToast("已存");
    } catch (e) {
      setToast(`Save failed: ${e instanceof Error ? e.message : e}`);
    } finally {
      setSaving(false);
    }
  }, [nl, skill, slug]);

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
      setToast(activate ? "已啟用 — 開始生效" : "已停用 — 回到草稿");
    } catch (e) {
      setToast(`操作失敗：${e instanceof Error ? e.message : e}`);
    } finally {
      setActivating(false);
    }
  }, [skill, slug]);

  if (loadError) return <Center>讀取失敗：{loadError}</Center>;
  if (!skill) return <Center>載入中...</Center>;

  const c = ROLE_COLORS[skill.role];

  return (
    <div style={{ background: TK.page, minHeight: "100vh", padding: "24px 24px 80px", fontFamily: FONT.sans, color: TK.ink }}>
      <div style={{ maxWidth: 1080, margin: "0 auto" }}>
        {/* Back */}
        <div style={{ marginBottom: 12 }}>
          <Link href="/skills" style={{
            color: TK.body, fontSize: 13, textDecoration: "none",
          }}>← Skills Library</Link>
        </div>

        {/* Header */}
        <div style={{
          background: TK.card, borderRadius: 14, padding: "18px 22px",
          boxShadow: "0 1px 3px rgba(15,18,30,.06)",
          marginBottom: 14,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <div style={{ font: `600 11px ${FONT.mono}`, color: TK.faint, letterSpacing: ".13em", textTransform: "uppercase" }}>
              SKILL · 自然語言 → DATA PIPELINE
            </div>
            <span style={{
              font: `600 10.5px ${FONT.mono}`,
              color: TK.indigo, background: TK.indigoTint,
              padding: "3px 8px", borderRadius: 6,
            }}>✦ 可當 MCP 工具</span>
            <span style={{
              font: `600 10.5px ${FONT.mono}`,
              color: c.color, background: c.tint, border: `1px solid ${c.border}`,
              padding: "3px 8px", borderRadius: 6,
            }}>{roleLabel(skill.role)}</span>
          </div>
          <h1 style={{ font: `700 22px ${FONT.sans}`, color: TK.ink, margin: "8px 0 4px" }}>{skill.name}</h1>
          <div style={{ fontSize: 13, color: TK.body }}>{skill.sub}</div>
        </div>

        {/* Two columns */}
        <div className="editor-cols" style={{
          display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16,
        }}>
          {/* Left: NL */}
          <Column>
            <ColumnHeader>你的描述 · 自然語言</ColumnHeader>
            <textarea
              value={nl}
              onChange={(e) => { setNl(e.target.value); setNlDirty(true); }}
              style={{
                flex: 1, minHeight: 320,
                padding: "14px 18px", border: "none", outline: "none",
                resize: "vertical",
                font: `15px/1.65 ${FONT.sans}`, color: TK.ink, background: "#fff",
              }}
            />
            <ColumnFooter>
              <span style={{ fontSize: 11, color: TK.faint }}>
                {nlDirty ? "未存（編輯中）" : "已存"}
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
                  {saving ? "Saving..." : "Save Draft"}
                </button>
                {skill.pipeline_id ? (
                  <>
                    <button onClick={() => handleOpenBuilder("rebuild")} disabled={opening} title="用 NL 重新跑 Agent，覆蓋目前 pipeline" style={{
                      font: `600 12px ${FONT.sans}`,
                      color: TK.body, background: "#fff",
                      border: `1px solid ${TK.divider}`,
                      padding: "7px 12px", borderRadius: 8, cursor: "pointer",
                    }}>
                      用 Agent 重新編譯
                    </button>
                    <button onClick={() => handleOpenBuilder("edit")} disabled={opening} title="開 Pipeline Builder 人手調 canvas，Agent 不會自動跑" style={{
                      font: `600 12px ${FONT.sans}`,
                      color: "#fff", background: TK.indigo, border: `1px solid ${TK.indigo}`,
                      padding: "7px 12px", borderRadius: 8, cursor: "pointer",
                    }}>
                      {opening ? "Opening…" : "編輯 pipeline →"}
                    </button>
                  </>
                ) : (
                  <button onClick={() => handleOpenBuilder("compile")} disabled={opening} style={{
                    font: `600 12px ${FONT.sans}`,
                    color: "#fff", background: TK.indigo, border: `1px solid ${TK.indigo}`,
                    padding: "7px 12px", borderRadius: 8, cursor: "pointer",
                  }}>
                    {opening ? "Opening…" : "用 Pipeline Builder 編譯 →"}
                  </button>
                )}
              </div>
            </ColumnFooter>
          </Column>

          {/* Right: Pipeline canvas thumb */}
          <Column>
            <ColumnHeader rightChip={`${pipeline.length} nodes`}>
              ✦ 編譯結果 · data pipeline
            </ColumnHeader>
            <div style={{ flex: 1, padding: "14px 18px" }}>
              <PipelineSvgThumb pipelineId={skill.pipeline_id} height={420} />
            </div>
          </Column>
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
          actionLabel={skill.role === "tool" ? "自動化此 Skill →" : "編輯自動化 →"}
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
        {active ? (
          <>● 已啟用 — 這個 Skill 已生效。</>
        ) : (
          <>○ 草稿狀態 — 尚未生效。Review 後按「啟用」才會開始運作。</>
        )}
      </div>
      {active ? (
        <button onClick={onDeactivate} disabled={busy} style={{
          font: `600 12px ${FONT.sans}`,
          color: "#92400e", background: "#fff", border: "1px solid #fde68a",
          padding: "7px 14px", borderRadius: 8, cursor: busy ? "wait" : "pointer",
          opacity: busy ? 0.6 : 1, whiteSpace: "nowrap",
        }}>
          {busy ? "…" : "停用"}
        </button>
      ) : (
        <button onClick={onActivate} disabled={busy} style={{
          font: `700 12.5px ${FONT.sans}`,
          color: "#fff", background: "#16a34a", border: "1px solid #16a34a",
          padding: "8px 18px", borderRadius: 8, cursor: busy ? "wait" : "pointer",
          opacity: busy ? 0.6 : 1, whiteSpace: "nowrap",
        }}>
          {busy ? "啟用中…" : "啟用 — 開始生效"}
        </button>
      )}
    </div>
  );
}

function AlarmCheck({ hasAlarm }: { hasAlarm: boolean }) {
  if (hasAlarm) {
    return (
      <div style={{
        marginTop: 14,
        background: TK.patrolTint, border: `1px solid ${TK.patrolBorder}`,
        borderRadius: 10, padding: "11px 16px",
        font: `500 12.5px ${FONT.sans}`, color: TK.patrolDeep,
      }}>
        ✓ 系統檢查：pipeline 含 alarm 判斷式 · 可自動化為 Auto Patrol（alarm 條件由你設、系統檢查）
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
      ℹ 系統檢查：pipeline 無 alarm · 只能作為 Data Check 或工具；要出 alarm 請在描述加入判斷條件再重新編譯。
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
