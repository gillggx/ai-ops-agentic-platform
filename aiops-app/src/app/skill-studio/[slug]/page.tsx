"use client";

/**
 * 画面 A — Skill Studio (3-stage pipeline overview + per-stage authoring).
 *
 * Per the OOC Skill Studio spec §3. Layout A (dual-column prose / compiled
 * rules) is the default; we ship A only in v1, the A/B/C toggle is
 * deferred. Lives at /skill-studio/[slug] — fully separate from the legacy
 * /skills/[slug] (Playbook) and /skills/[slug]/dry-run paths so the rest
 * of the app stays untouched while this iterates.
 *
 * State:
 *   - Active stage (detect / diagnose / recover) — Stage Ribbon click
 *   - Per-stage prose (local edit buffer, flushed on Save)
 *   - Per-stage compiled rules (from server; refreshed by Re-compile)
 *   - Inline Dry-run banner (mock for v1; Phase 4 wires real run)
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import type {
  SkillStage, StageKind, DetectRule, DiagnoseRule, RecoverRule,
} from "@/components/skill-studio/types";
import { KIND_META, KIND_ORDER, SAFETY_META } from "@/components/skill-studio/types";

const STUDIO_BG = "#f3f4f6";
const CARD_BG = "#fff";
const INK = "#23252b";
const TITLE = "#1c1d22";
const BODY = "#6b6f78";
const FAINT = "#9398a1";
const BORDER = "#eef0f2";
const DIVIDER = "#f1f2f4";
const BLACK = "#1c1d22";
const FONT_UI = "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
const FONT_MONO = "ui-monospace, 'SF Mono', Menlo, monospace";

export default function SkillStudioPage() {
  const params = useParams<{ slug: string }>();
  const slug = params?.slug ?? "";

  const [stages, setStages] = useState<Record<StageKind, SkillStage> | null>(null);
  const [active, setActive] = useState<StageKind>("diagnose");
  const [loadError, setLoadError] = useState<string | null>(null);

  const [prose, setProse] = useState<string>("");
  const [proseDirty, setProseDirty] = useState(false);
  const [compiling, setCompiling] = useState(false);
  const [saving, setSaving] = useState(false);
  const [activating, setActivating] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const [toast, setToast] = useState<string>("");

  // ── Load ──────────────────────────────────────────────────────────────────

  const loadStages = useCallback(async () => {
    if (!slug) return;
    try {
      const res = await fetch(`/api/skill-studio/${encodeURIComponent(slug)}/stages`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const env = await res.json();
      const list = (env?.data ?? env) as SkillStage[];
      const byKind: Partial<Record<StageKind, SkillStage>> = {};
      for (const s of list) byKind[s.kind] = s;
      setStages(byKind as Record<StageKind, SkillStage>);
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e));
    }
  }, [slug]);

  useEffect(() => { loadStages(); }, [loadStages]);

  // Sync prose buffer when active stage changes.
  useEffect(() => {
    if (stages && stages[active]) {
      setProse(stages[active].prose);
      setProseDirty(false);
    }
  }, [active, stages]);

  // Auto-dismiss toast.
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 2400);
    return () => clearTimeout(t);
  }, [toast]);

  // ── Actions ───────────────────────────────────────────────────────────────

  const activeStage = stages?.[active] ?? null;
  const isStable = activeStage?.status === "stable";

  const rules = useMemo<unknown[]>(() => {
    if (!activeStage) return [];
    try { return JSON.parse(activeStage.compiled_rules) as unknown[]; }
    catch { return []; }
  }, [activeStage]);

  const handleSaveProse = useCallback(async () => {
    if (!activeStage) return;
    setSaving(true);
    try {
      const res = await fetch(`/api/skill-studio/${encodeURIComponent(slug)}/stages/${active}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prose }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const env = await res.json();
      const saved = (env?.data ?? env) as SkillStage;
      setStages(s => s ? { ...s, [active]: saved } : s);
      setProseDirty(false);
      setToast("Prose 已存");
    } catch (e) {
      setToast(`Save failed: ${e instanceof Error ? e.message : e}`);
    } finally {
      setSaving(false);
    }
  }, [active, activeStage, prose, slug]);

  const handleCompile = useCallback(async () => {
    if (!activeStage) return;
    setCompiling(true);
    try {
      const res = await fetch(`/api/skill-studio/${encodeURIComponent(slug)}/stages/${active}/compile`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prose }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const env = await res.json();
      const compiledRules = (env?.data?.compiledRules ?? env?.data?.compiled_rules
                             ?? env?.compiledRules ?? env?.compiled_rules ?? "[]") as string;
      // Persist the compiled rules too (saveStage accepts them). Phase 2 stub
      // doesn't auto-persist server-side — the UI controls "save my edit".
      const putRes = await fetch(`/api/skill-studio/${encodeURIComponent(slug)}/stages/${active}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prose, compiled_rules: compiledRules }),
      });
      if (putRes.ok) {
        const putEnv = await putRes.json();
        const saved = (putEnv?.data ?? putEnv) as SkillStage;
        setStages(s => s ? { ...s, [active]: saved } : s);
        setProseDirty(false);
      } else {
        // PUT may reject compiled_rules; just update local state for preview.
        setStages(s => s ? {
          ...s,
          [active]: { ...s[active], compiled_rules: compiledRules },
        } : s);
      }
      setToast("已重新編譯");
    } catch (e) {
      setToast(`Compile failed: ${e instanceof Error ? e.message : e}`);
    } finally {
      setCompiling(false);
    }
  }, [active, activeStage, prose, slug]);

  const handleActivate = useCallback(async () => {
    if (!activeStage) return;
    if (!confirm(`Activate ${active.toUpperCase()} stage? 凍結後規則由 code 執行，每次一致。`)) return;
    setActivating(true);
    try {
      const res = await fetch(`/api/skill-studio/${encodeURIComponent(slug)}/stages/${active}/activate`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const env = await res.json();
      const saved = (env?.data ?? env) as SkillStage;
      setStages(s => s ? { ...s, [active]: saved } : s);
      setToast(`${active.toUpperCase()} stage activated · v${saved.version}`);
    } catch (e) {
      setToast(`Activate failed: ${e instanceof Error ? e.message : e}`);
    } finally {
      setActivating(false);
    }
  }, [active, activeStage, slug]);

  const handleDryRunInline = useCallback(() => {
    // Phase 1: just show an inline banner pointing the user at the dedicated
    // dry-run page for DIAGNOSE. Detect / recover dry-run is Phase 5+.
    if (active === "diagnose") {
      setBanner(`Dry-run 在另一個專門頁面跑（見 → "${slug} / Checklist Editor"）。點 ▸ 進入。`);
    } else {
      setBanner(`${active.toUpperCase()} stage 的 dry-run 在 Phase 5 才接上。目前僅供編輯 / 編譯預覽。`);
    }
  }, [active, slug]);

  if (loadError) {
    return <CenterMessage>讀取 stages 失敗：{loadError}</CenterMessage>;
  }
  if (!stages || !activeStage) {
    return <CenterMessage>載入中...</CenterMessage>;
  }

  return (
    <div style={{ background: STUDIO_BG, minHeight: "100vh", padding: "32px 24px 80px" }}>
      <div style={{ maxWidth: 1080, margin: "0 auto" }}>
        {/* ── Toolbar ── */}
        <Toolbar slug={slug} />

        {/* ── Stage Ribbon ── */}
        <StageRibbon stages={stages} active={active} onSelect={setActive} />

        {/* ── Section header ── */}
        <SectionHeader
          active={active}
          stage={activeStage}
          onDryRun={handleDryRunInline}
        />

        {/* ── Inline dry-run banner ── */}
        {banner && (
          <InlineBanner
            text={banner}
            tint={KIND_META[active].tint}
            color={KIND_META[active].deep}
            onClose={() => setBanner(null)}
            actionHref={active === "diagnose" ? `/skill-studio/${encodeURIComponent(slug)}/checklist` : null}
          />
        )}

        {/* ── Two-column body ── */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 16,
          marginTop: 14,
        }} className="studio-cols">
          {/* Left: prose */}
          <ProseColumn
            prose={prose}
            setProse={(v) => { setProse(v); setProseDirty(true); }}
            disabled={isStable}
            saving={saving}
            compiling={compiling}
            dirty={proseDirty}
            onSave={handleSaveProse}
            onRecompile={handleCompile}
            color={KIND_META[active].deep}
          />
          {/* Right: compiled rules */}
          <CompiledColumn
            kind={active}
            rules={rules}
            status={activeStage.status}
            version={activeStage.version}
            onActivate={handleActivate}
            activating={activating}
            disabled={isStable && false /* allow re-activate to bump version */}
          />
        </div>

        {/* ── Contract bar ── */}
        <ContractBar active={active} />
      </div>

      {toast && <Toast text={toast} />}

      <style>{`
        @media (max-width: 800px) {
          .studio-cols { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  );
}

// ── Toolbar ──────────────────────────────────────────────────────────────────

function Toolbar({ slug }: { slug: string }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      marginBottom: 18,
    }}>
      <div style={{ font: `500 13px ${FONT_UI}`, color: BODY }}>
        <Link href="/skills" style={{ color: BODY, textDecoration: "none" }}>Skills Library</Link>
        <span style={{ margin: "0 8px", color: FAINT }}>/</span>
        <span style={{ color: TITLE, fontWeight: 600 }}>{slug}</span>
      </div>
      <Link
        href={`/skill-studio/${encodeURIComponent(slug)}/checklist`}
        style={{
          font: `600 13px ${FONT_UI}`,
          color: BLACK,
          textDecoration: "none",
          padding: "8px 14px",
          borderRadius: 8,
          border: `1px solid ${BORDER}`,
          background: "#fff",
        }}
      >
        Checklist Editor →
      </Link>
    </div>
  );
}

// ── Stage Ribbon ─────────────────────────────────────────────────────────────

function StageRibbon({
  stages, active, onSelect,
}: {
  stages: Record<StageKind, SkillStage>;
  active: StageKind;
  onSelect: (k: StageKind) => void;
}) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12,
      background: CARD_BG, borderRadius: 14,
      boxShadow: "0 1px 3px rgba(15,18,30,.08), 0 12px 40px rgba(15,18,30,.06)",
      padding: 14,
      marginBottom: 14,
    }}>
      {KIND_ORDER.map((kind, i) => (
        <>
          <StageCard
            key={kind}
            kind={kind}
            isActive={kind === active}
            stage={stages[kind]}
            onClick={() => onSelect(kind)}
          />
          {i < KIND_ORDER.length - 1 && (
            <ContractBadge text={KIND_META[KIND_ORDER[i + 1]].contractIn ?? ""} key={`b-${kind}`} />
          )}
        </>
      ))}
    </div>
  );
}

function StageCard({
  kind, isActive, stage, onClick,
}: {
  kind: StageKind;
  isActive: boolean;
  stage: SkillStage;
  onClick: () => void;
}) {
  const m = KIND_META[kind];
  return (
    <button
      onClick={onClick}
      style={{
        flex: 1,
        textAlign: "left",
        padding: "12px 16px",
        borderRadius: 11,
        border: `1.5px solid ${isActive ? m.color : BORDER}`,
        background: isActive ? m.tint : "#fff",
        cursor: "pointer",
        font: FONT_UI,
      }}
    >
      <div style={{
        font: `600 10.5px ${FONT_MONO}`,
        letterSpacing: ".13em",
        color: m.color,
        textTransform: "uppercase",
        marginBottom: 4,
      }}>
        {m.en} · STAGE {KIND_ORDER.indexOf(kind) + 1} / 3
      </div>
      <div style={{ font: `650 16px ${FONT_UI}`, color: TITLE, marginBottom: 4 }}>
        {m.zh}
      </div>
      <div style={{ fontSize: 12, color: BODY, marginBottom: 6, lineHeight: 1.4 }}>
        {m.tagline}
      </div>
      <span style={{
        display: "inline-block", padding: "2px 7px",
        borderRadius: 6,
        font: `600 10px ${FONT_MONO}`,
        background: stage.status === "stable" ? "#e6f6f0" : "#f2f3f5",
        color: stage.status === "stable" ? "#0b7a55" : "#5b6470",
      }}>
        {stage.status} · v{stage.version}
      </span>
    </button>
  );
}

function ContractBadge({ text }: { text: string }) {
  return (
    <div style={{
      padding: "5px 9px",
      borderRadius: 6,
      background: "#f7f8fc",
      border: `1px solid ${BORDER}`,
      font: `600 10.5px ${FONT_MONO}`,
      color: BODY,
      whiteSpace: "nowrap",
    }}>
      {text}
    </div>
  );
}

// ── Section header ──────────────────────────────────────────────────────────

function SectionHeader({
  active, stage, onDryRun,
}: {
  active: StageKind;
  stage: SkillStage;
  onDryRun: () => void;
}) {
  const m = KIND_META[active];
  return (
    <div style={{
      background: CARD_BG, borderRadius: 14,
      boxShadow: "0 1px 3px rgba(15,18,30,.08), 0 12px 40px rgba(15,18,30,.06)",
      padding: "18px 22px",
      marginBottom: 14,
      display: "flex", justifyContent: "space-between", alignItems: "center",
    }}>
      <div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <h2 style={{ font: `650 20px ${FONT_UI}`, color: TITLE, margin: 0 }}>
            {m.zh} <span style={{ color: m.deep, fontSize: 14, marginLeft: 6 }}>{m.en}</span>
          </h2>
          <span style={{
            font: `600 10.5px ${FONT_MONO}`,
            color: m.color, background: m.tint,
            padding: "3px 8px", borderRadius: 6,
          }}>
            STAGE {KIND_ORDER.indexOf(active) + 1} / 3
          </span>
        </div>
        <div style={{ fontSize: 12, color: BODY, marginTop: 4 }}>{m.tagline}</div>
      </div>
      <button
        onClick={onDryRun}
        style={{
          font: `600 13px ${FONT_UI}`, color: "#fff",
          background: BLACK, border: `1px solid ${BLACK}`,
          padding: "9px 15px", borderRadius: 9, cursor: "pointer",
        }}
      >
        ▸ Dry-run 這段
      </button>
    </div>
  );
}

function InlineBanner({
  text, tint, color, onClose, actionHref,
}: {
  text: string;
  tint: string;
  color: string;
  onClose: () => void;
  actionHref: string | null;
}) {
  return (
    <div style={{
      background: tint,
      border: `1px solid ${color}33`,
      borderRadius: 10,
      padding: "10px 14px",
      marginBottom: 14,
      display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
    }}>
      <span style={{ fontSize: 13, color }}>{text}</span>
      <div style={{ display: "flex", gap: 8 }}>
        {actionHref && (
          <Link href={actionHref} style={{
            font: `600 12px ${FONT_UI}`, color,
            textDecoration: "none",
            padding: "5px 10px", borderRadius: 6,
            border: `1px solid ${color}55`, background: "#fff",
          }}>
            ▸ 進入
          </Link>
        )}
        <button onClick={onClose} style={{
          background: "transparent", border: "none", cursor: "pointer",
          color: BODY, fontSize: 18, padding: 0, lineHeight: 1,
        }}>×</button>
      </div>
    </div>
  );
}

// ── Prose column ────────────────────────────────────────────────────────────

function ProseColumn({
  prose, setProse, disabled, saving, compiling, dirty, onSave, onRecompile, color,
}: {
  prose: string;
  setProse: (v: string) => void;
  disabled: boolean;
  saving: boolean;
  compiling: boolean;
  dirty: boolean;
  onSave: () => void;
  onRecompile: () => void;
  color: string;
}) {
  return (
    <div style={{
      background: CARD_BG, borderRadius: 14,
      boxShadow: "0 1px 3px rgba(15,18,30,.08), 0 12px 40px rgba(15,18,30,.06)",
      display: "flex", flexDirection: "column",
      overflow: "hidden",
    }}>
      <div style={{
        padding: "12px 16px", borderBottom: `1px solid ${BORDER}`,
        font: `600 10.5px ${FONT_MONO}`,
        letterSpacing: ".13em",
        color: BODY,
        textTransform: "uppercase",
      }}>
        你的描述 · 自然語言
      </div>
      <textarea
        value={prose}
        onChange={(e) => setProse(e.target.value)}
        disabled={disabled}
        style={{
          flex: 1,
          minHeight: 280,
          padding: "14px 16px",
          border: "none",
          outline: "none",
          resize: "vertical",
          font: `15px/1.6 ${FONT_UI}`,
          color: INK,
          background: disabled ? "#fafbfc" : "#fff",
        }}
      />
      <div style={{
        padding: "10px 16px", borderTop: `1px solid ${BORDER}`,
        display: "flex", justifyContent: "space-between", alignItems: "center",
        background: "#fbfbfc",
      }}>
        <div style={{ fontSize: 11, color: FAINT }}>
          {disabled
            ? "stable 階段 prose 唯讀 — 重新編譯前先 deactivate（Phase 7）"
            : (dirty ? "未存（編輯中）" : "已存")}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={onSave}
            disabled={disabled || !dirty || saving}
            style={{
              font: `600 12px ${FONT_UI}`,
              color: BLACK, background: "#fff",
              border: `1px solid ${BORDER}`,
              padding: "7px 12px", borderRadius: 8,
              cursor: (disabled || !dirty) ? "not-allowed" : "pointer",
              opacity: (disabled || !dirty) ? 0.45 : 1,
            }}
          >
            {saving ? "Saving..." : "Save Draft"}
          </button>
          <button
            onClick={onRecompile}
            disabled={disabled || compiling}
            style={{
              font: `600 12px ${FONT_UI}`,
              color: "#fff", background: color, border: `1px solid ${color}`,
              padding: "7px 12px", borderRadius: 8,
              cursor: disabled ? "not-allowed" : "pointer",
              opacity: disabled ? 0.5 : 1,
            }}
          >
            {compiling ? "Compiling…" : "重新編譯 ↻"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Compiled column ─────────────────────────────────────────────────────────

function CompiledColumn({
  kind, rules, status, version, onActivate, activating, disabled,
}: {
  kind: StageKind;
  rules: unknown[];
  status: SkillStage["status"];
  version: string;
  onActivate: () => void;
  activating: boolean;
  disabled: boolean;
}) {
  return (
    <div style={{
      background: CARD_BG, borderRadius: 14,
      boxShadow: "0 1px 3px rgba(15,18,30,.08), 0 12px 40px rgba(15,18,30,.06)",
      display: "flex", flexDirection: "column",
      overflow: "hidden",
    }}>
      <div style={{
        padding: "12px 16px", borderBottom: `1px solid ${BORDER}`,
        font: `600 10.5px ${FONT_MONO}`,
        letterSpacing: ".13em",
        color: BODY,
        textTransform: "uppercase",
        display: "flex", justifyContent: "space-between", alignItems: "center",
      }}>
        <span>✦ 編譯結果 · code 執行</span>
        <span style={{ color: status === "stable" ? "#0b7a55" : FAINT }}>
          {status} · v{version}
        </span>
      </div>
      <div style={{ flex: 1, padding: "12px 16px", overflowY: "auto", maxHeight: 460 }}>
        {rules.length === 0 ? (
          <div style={{ color: FAINT, fontSize: 13, padding: "20px 0", textAlign: "center" }}>
            尚未編譯 — 在左欄寫 prose，按「重新編譯 ↻」生成 rules。
          </div>
        ) : (
          <RuleList kind={kind} rules={rules} />
        )}
      </div>
      <div style={{
        padding: "10px 16px", borderTop: `1px solid ${BORDER}`,
        display: "flex", justifyContent: "space-between", alignItems: "center",
        background: "#fbfbfc",
      }}>
        <div style={{ fontSize: 11, color: FAINT }}>
          Activate 後凍結 · 每次一致
        </div>
        <button
          onClick={onActivate}
          disabled={disabled || activating || rules.length === 0}
          style={{
            font: `600 12px ${FONT_UI}`,
            color: "#fff", background: BLACK, border: `1px solid ${BLACK}`,
            padding: "7px 12px", borderRadius: 8,
            cursor: (disabled || rules.length === 0) ? "not-allowed" : "pointer",
            opacity: (disabled || rules.length === 0) ? 0.5 : 1,
          }}
        >
          {activating ? "Activating…" : (status === "stable" ? "Re-activate ↻" : "Activate")}
        </button>
      </div>
    </div>
  );
}

function RuleList({ kind, rules }: { kind: StageKind; rules: unknown[] }) {
  if (kind === "detect") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {(rules as DetectRule[]).map((r) => (
          <div key={r.id} style={ruleCard}>
            <KV k="WHEN" v={r.when} />
            <KV k="FOR"  v={r.for} />
            <KV k="IF"   v={r.if} />
            <KV k="THEN" v={r.then} highlight />
          </div>
        ))}
      </div>
    );
  }
  if (kind === "diagnose") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {(rules as DiagnoseRule[]).map((r) => (
          <div key={r.id} style={ruleRow}>
            <span style={{ font: `600 11px ${FONT_MONO}`, color: BODY, width: 28 }}>{r.id}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ font: `600 13px ${FONT_UI}`, color: INK }}>{r.title}</div>
              <div style={{ fontSize: 11, color: FAINT, marginTop: 2 }}>
                dim={r.dim} · {r.operator} {r.threshold}
              </div>
            </div>
            <span style={{
              font: `600 10.5px ${FONT_MONO}`, color: BODY,
              padding: "3px 7px", borderRadius: 5, background: "#f2f3f5",
            }}>→ Finding</span>
          </div>
        ))}
      </div>
    );
  }
  // recover
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {(rules as RecoverRule[]).map((r) => {
        const s = SAFETY_META[r.safety] ?? SAFETY_META.notify;
        return (
          <div key={r.id} style={ruleRow}>
            <span style={{ font: `600 11px ${FONT_MONO}`, color: BODY, width: 28 }}>{r.id}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ font: `600 13px ${FONT_UI}`, color: INK }}>{r.pattern}</div>
              <div style={{ fontSize: 12, color: BODY, marginTop: 2 }}>→ {r.action}</div>
            </div>
            <span style={{
              font: `600 10.5px ${FONT_MONO}`,
              color: s.color, background: s.bg,
              padding: "3px 8px", borderRadius: 6,
            }}>{s.label}</span>
          </div>
        );
      })}
    </div>
  );
}

// ── Contract bar ────────────────────────────────────────────────────────────

function ContractBar({ active }: { active: StageKind }) {
  const m = KIND_META[active];
  return (
    <div style={{
      marginTop: 14,
      padding: "10px 16px", borderRadius: 10,
      background: "#fbfbfc", border: `1px solid ${DIVIDER}`,
      display: "flex", justifyContent: "space-between", alignItems: "center",
      font: `12px ${FONT_MONO}`,
    }}>
      <span style={{ color: BODY }}>
        <strong style={{ color: INK }}>in:</strong> {m.contractIn ?? "—"}
        <span style={{ margin: "0 8px", color: FAINT }}>→</span>
        <strong style={{ color: INK }}>out:</strong> {m.contractOut}
      </span>
      <span style={{ color: FAINT, fontSize: 11 }}>
        階段契約固定 · 可單獨測試
      </span>
    </div>
  );
}

// ── Small components ────────────────────────────────────────────────────────

function KV({ k, v, highlight }: { k: string; v: string; highlight?: boolean }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "60px 1fr", gap: 8, fontSize: 12, marginBottom: 4 }}>
      <span style={{ font: `600 11px ${FONT_MONO}`, color: BODY }}>{k}</span>
      <span style={{
        fontFamily: FONT_MONO,
        color: highlight ? "#0b7a55" : INK,
        fontWeight: highlight ? 600 : 400,
      }}>{v}</span>
    </div>
  );
}

function CenterMessage({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ background: STUDIO_BG, minHeight: "100vh",
                   display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ background: "#fff", padding: "24px 30px", borderRadius: 12,
                     boxShadow: "0 1px 3px rgba(15,18,30,.1)", color: BODY }}>
        {children}
      </div>
    </div>
  );
}

function Toast({ text }: { text: string }) {
  return (
    <div style={{
      position: "fixed", bottom: 28, left: "50%", transform: "translateX(-50%)",
      background: BLACK, color: "#fff",
      padding: "9px 16px", borderRadius: 9,
      fontSize: 13, boxShadow: "0 8px 24px rgba(0,0,0,.25)",
      zIndex: 60, maxWidth: 480,
    }}>{text}</div>
  );
}

const ruleCard: React.CSSProperties = {
  padding: "12px 14px",
  border: `1px solid ${BORDER}`,
  borderRadius: 9,
  background: "#fafbfc",
};

const ruleRow: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 10,
  padding: "9px 12px",
  border: `1px solid ${BORDER}`,
  borderRadius: 8,
  background: "#fff",
};
