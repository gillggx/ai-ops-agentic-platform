"use client";

/**
 * Skills v2 — Try Run (試跑).
 *
 * A read-only dry-run of the skill's bound pipeline from the Editor: collect
 * the pipeline's declared inputs inline, execute via the same /execute path
 * the Pipeline Builder "Run" button uses, then show an inline verdict summary
 * plus the full PipelineResultsPanel (charts / evidence) on demand.
 *
 * Read-only: /execute writes a pipeline_runs row but does NOT go through the
 * skill-automation dispatch path, so it raises NO alarm and writes NO
 * skill_run. Safe to click repeatedly while tuning the pipeline.
 */

import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";
import { executePipeline } from "@/lib/pipeline-builder/api";
import type { ExecuteResponse, PipelineJSON } from "@/lib/pipeline-builder/types";
import PipelineResultsPanel from "@/components/pipeline-builder/PipelineResultsPanel";
import { TK, FONT } from "./tokens";

interface Props {
  pipelineId: number;
}

export default function SkillTryRunPanel({ pipelineId }: Props) {
  const t = useTranslations("skills.tryRun");
  const [expanded, setExpanded] = useState(false);
  const [pj, setPj] = useState<PipelineJSON | null>(null);
  const [loading, setLoading] = useState(false);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ExecuteResponse | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);

  const loadPipeline = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const res = await fetch(`/api/pipeline-builder/pipelines/${pipelineId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const env = await res.json();
      const record = env?.data ?? env;
      const raw = record?.pipeline_json ?? record;
      const parsed: PipelineJSON = typeof raw === "string" ? JSON.parse(raw) : raw;
      setPj(parsed);
      const seed: Record<string, string> = {};
      for (const inp of parsed.inputs ?? []) {
        const v = inp.example ?? inp.default;
        seed[inp.name] = v != null ? String(v) : "";
      }
      setInputs(seed);
    } catch (e) {
      setError(t("loadPipelineFailed", { error: e instanceof Error ? e.message : String(e) }));
    } finally {
      setLoading(false);
    }
  }, [pipelineId, t]);

  const handleExpand = useCallback(() => {
    setExpanded(true);
    if (!pj) void loadPipeline();
  }, [pj, loadPipeline]);

  const handleRun = useCallback(async () => {
    if (!pj) return;
    setRunning(true); setError(null); setResult(null);
    try {
      const coerced: Record<string, unknown> = {};
      for (const inp of pj.inputs ?? []) {
        const raw = (inputs[inp.name] ?? "").trim();
        if (raw === "") continue;
        coerced[inp.name] =
          inp.type === "integer" || inp.type === "number" ? Number(raw)
          : inp.type === "boolean" ? raw === "true"
          : raw;
      }
      const res = await executePipeline(pj, coerced);
      setResult(res);
      if (res.status === "validation_error" || res.status === "failed") {
        setError(res.error_message || firstNodeError(res) || t("runStatus", { status: res.status }));
      } else {
        setPanelOpen(true);
      }
    } catch (e) {
      setError(t("runFailed", { error: e instanceof Error ? e.message : String(e) }));
    } finally {
      setRunning(false);
    }
  }, [pj, inputs, t]);

  if (!expanded) {
    return (
      <div style={{ marginTop: 14 }}>
        <button onClick={handleExpand} style={{
          font: `600 13px ${FONT.sans}`,
          color: "#fff", background: TK.black, border: `1px solid ${TK.black}`,
          padding: "9px 16px", borderRadius: 9, cursor: "pointer",
        }}>
          {t("expandButton")}
        </button>
      </div>
    );
  }

  const inputDefs = pj?.inputs ?? [];
  const summary = result?.result_summary ?? null;

  return (
    <div style={{
      marginTop: 14, background: TK.card, borderRadius: 14,
      boxShadow: "0 1px 3px rgba(15,18,30,.06)", padding: "16px 20px",
    }}>
      <div style={{
        font: `600 11px ${FONT.mono}`, letterSpacing: ".13em",
        color: TK.faint, textTransform: "uppercase", marginBottom: 4,
      }}>{t("eyebrow")}</div>
      <div style={{ fontSize: 12.5, color: TK.body, marginBottom: 12 }}>
        {t("description")}
      </div>

      {loading && <div style={{ fontSize: 13, color: TK.faint }}>{t("loadingPipeline")}</div>}

      {!loading && pj && (
        <>
          {/* Inputs */}
          {inputDefs.length === 0 ? (
            <div style={{ fontSize: 12.5, color: TK.faint, marginBottom: 12 }}>
              {t("noInputs")}
            </div>
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginBottom: 14 }}>
              {inputDefs.map(inp => (
                <label key={inp.name} style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 180 }}>
                  <span style={{ font: `600 12px ${FONT.mono}`, color: TK.body }}>
                    {inp.name}
                    {inp.required && <span style={{ color: "#b42318" }}> *</span>}
                    <span style={{ color: TK.faint, fontWeight: 400 }}> · {inp.type}</span>
                  </span>
                  <input
                    value={inputs[inp.name] ?? ""}
                    onChange={(e) => setInputs(prev => ({ ...prev, [inp.name]: e.target.value }))}
                    placeholder={inp.example != null ? String(inp.example) : inp.description ?? ""}
                    style={{
                      font: `13px ${FONT.sans}`, color: TK.ink,
                      padding: "7px 10px", border: `1px solid ${TK.divider}`,
                      borderRadius: 8, outline: "none", minWidth: 180,
                    }}
                  />
                </label>
              ))}
            </div>
          )}

          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <button onClick={handleRun} disabled={running} style={{
              font: `600 13px ${FONT.sans}`,
              color: "#fff", background: running ? TK.faint : TK.indigo,
              border: `1px solid ${running ? TK.faint : TK.indigo}`,
              padding: "9px 18px", borderRadius: 9, cursor: running ? "default" : "pointer",
            }}>
              {running ? t("running") : t("run")}
            </button>
            {summary && !error && (
              <VerdictChip summary={summary} onOpen={() => setPanelOpen(true)} />
            )}
          </div>

          {error && (
            <div style={{
              marginTop: 12, padding: "9px 12px", borderRadius: 8,
              background: "#fef3f2", color: "#b42318",
              font: `500 12.5px ${FONT.sans}`, border: "1px solid #fecaca",
              whiteSpace: "pre-wrap",
            }}>{error}</div>
          )}
        </>
      )}

      {!loading && !pj && error && (
        <div style={{ fontSize: 13, color: "#b42318" }}>{error}</div>
      )}

      <PipelineResultsPanel
        open={panelOpen}
        onClose={() => setPanelOpen(false)}
        summary={summary}
        nodeResults={result?.node_results ?? {}}
      />
    </div>
  );
}

/** When a run fails, surface the first failing node's error so the user sees
 *  WHY (e.g. "n2 · column 'spc_charts' not in data") instead of a bare "failed". */
function firstNodeError(res: ExecuteResponse): string | null {
  for (const [nodeId, nr] of Object.entries(res.node_results ?? {})) {
    if (nr?.status === "failed" && nr.error) return `${nodeId} · ${nr.error}`;
  }
  return null;
}

function VerdictChip({ summary, onOpen }: {
  summary: NonNullable<ExecuteResponse["result_summary"]>;
  onOpen: () => void;
}) {
  const t = useTranslations("skills.tryRun");
  const triggered = summary.triggered;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
      <span style={{
        font: `700 12.5px ${FONT.sans}`,
        color: triggered ? "#b42318" : "#0b7a55",
        background: triggered ? "#fef3f2" : "#e6f6f0",
        border: `1px solid ${triggered ? "#fecaca" : "#c5e7d3"}`,
        padding: "5px 11px", borderRadius: 999,
      }}>
        {triggered ? t("triggered") : t("notTriggered")}
      </span>
      <span style={{ fontSize: 12, color: TK.faint }}>
        {t("evidenceSummary", { rows: summary.evidence_rows, charts: summary.charts.length })}
      </span>
      <button onClick={onOpen} style={{
        font: `600 12px ${FONT.sans}`,
        color: TK.indigo, background: "#fff", border: `1px solid ${TK.indigo}`,
        padding: "5px 12px", borderRadius: 8, cursor: "pointer",
      }}>
        {t("viewFullResult")}
      </button>
    </div>
  );
}
