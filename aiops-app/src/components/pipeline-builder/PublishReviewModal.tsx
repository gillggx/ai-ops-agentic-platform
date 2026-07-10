"use client";

import { useEffect, useState } from "react";
import { getDraftDoc, publishPipeline, type DraftDoc } from "@/lib/pipeline-builder/api";

interface Props {
  open: boolean;
  pipelineId: number | null;
  onClose: () => void;
  onPublished: (slug: string) => void;
}

export default function PublishReviewModal({ open, pipelineId, onClose, onPublished }: Props) {
  const [loading, setLoading] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [doc, setDoc] = useState<DraftDoc | null>(null);

  useEffect(() => {
    if (!open || pipelineId == null) return;
    setError(null);
    setLoading(true);
    getDraftDoc(pipelineId)
      .then((d) => setDoc(d))
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [open, pipelineId]);

  if (!open) return null;

  const handleRegen = async () => {
    if (pipelineId == null) return;
    setLoading(true);
    setError(null);
    try {
      const d = await getDraftDoc(pipelineId);
      setDoc(d);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handlePublish = async () => {
    if (pipelineId == null || !doc) return;
    setPublishing(true);
    setError(null);
    try {
      const result = await publishPipeline(pipelineId, doc);
      onPublished(result.published_slug || doc.slug);
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPublishing(false);
    }
  };

  const setField = <K extends keyof DraftDoc>(key: K, value: DraftDoc[K]) => {
    setDoc((prev) => (prev ? { ...prev, [key]: value } : prev));
  };

  return (
    <div
      data-testid="publish-review-modal"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15,23,42,0.55)",
        zIndex: 3000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 760,
          maxWidth: "92vw",
          maxHeight: "90vh",
          background: "#fff",
          borderRadius: 8,
          boxShadow: "0 8px 24px rgba(15,23,42,0.2)",
          padding: 22,
          fontFamily: "system-ui, -apple-system, sans-serif",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: "#0F172A" }}>
            📘 Publish — 審核 Agent-facing 文件
          </div>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            <button onClick={handleRegen} disabled={loading} style={ghostBtn}>
              🔄 重新生成
            </button>
            <button onClick={onClose} style={ghostBtn}>
              取消
            </button>
            <button
              onClick={handlePublish}
              disabled={publishing || !doc}
              style={{
                ...primaryBtn,
                cursor: publishing || !doc ? "not-allowed" : "pointer",
                opacity: publishing || !doc ? 0.5 : 1,
              }}
            >
              {publishing ? "Publishing…" : "✔ 確認發佈"}
            </button>
          </div>
        </div>

        <div style={{ fontSize: 11, color: "#64748B", marginBottom: 12, lineHeight: 1.6 }}>
          這份文件會被註冊進 Skill Registry，Agent 透過 <code>search_published_skills</code> 檢索到。
          請確認 <b>use_case</b> + <b>when_to_use</b> 描述清楚何時該使用本 Skill。
        </div>

        {error && (
          <div
            style={{
              padding: 10,
              background: "#FEF2F2",
              color: "#B91C1C",
              border: "1px solid #FECACA",
              borderRadius: 4,
              fontSize: 12,
              marginBottom: 10,
            }}
          >
            {error}
          </div>
        )}

        {loading && <div style={{ padding: 40, textAlign: "center", color: "#94A3B8" }}>生成中…</div>}

        {doc && !loading && (
          <div style={{ overflowY: "auto", flex: 1, paddingRight: 6 }}>
            <Field label="slug（唯一識別符）" hint="Agent 以此定位 Skill；建議鎖定不改">
              <input
                value={doc.slug}
                onChange={(e) => setField("slug", e.target.value)}
                style={inputStyle}
              />
            </Field>

            <Field label="name">
              <input
                value={doc.name}
                onChange={(e) => setField("name", e.target.value)}
                style={inputStyle}
              />
            </Field>

            <Field label="use_case（Agent RAG 最重要欄位）">
              <textarea
                value={doc.use_case}
                onChange={(e) => setField("use_case", e.target.value)}
                rows={4}
                style={{ ...inputStyle, fontFamily: "inherit", resize: "vertical" }}
              />
            </Field>

            <Field label="when_to_use（觸發情境，每行一條）">
              <textarea
                value={doc.when_to_use.join("\n")}
                onChange={(e) =>
                  setField(
                    "when_to_use",
                    e.target.value.split("\n").map((s) => s.trim()).filter(Boolean),
                  )
                }
                rows={Math.max(3, doc.when_to_use.length)}
                style={{ ...inputStyle, fontFamily: "inherit", resize: "vertical" }}
              />
            </Field>

            <Field label="tags（逗號分隔）">
              <input
                value={doc.tags.join(", ")}
                onChange={(e) =>
                  setField(
                    "tags",
                    e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                  )
                }
                style={inputStyle}
              />
            </Field>

            <Field label="inputs_schema（pipeline.inputs 自動帶入，不可改名）">
              <pre style={previewBox}>{JSON.stringify(doc.inputs_schema, null, 2)}</pre>
            </Field>

            <Field label="outputs_schema">
              <pre style={previewBox}>{JSON.stringify(doc.outputs_schema, null, 2)}</pre>
            </Field>

            <Field label="example_invocation">
              <pre style={previewBox}>
                {JSON.stringify(doc.example_invocation ?? {}, null, 2)}
              </pre>
            </Field>
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <label
        style={{
          display: "block",
          fontSize: 10,
          fontWeight: 700,
          color: "#475569",
          letterSpacing: "0.05em",
          textTransform: "uppercase",
          marginBottom: 4,
        }}
      >
        {label}
        {hint && (
          <span
            style={{
              marginLeft: 8,
              fontSize: 10,
              color: "#94A3B8",
              fontWeight: 400,
              textTransform: "none",
              letterSpacing: 0,
            }}
          >
            {hint}
          </span>
        )}
      </label>
      {children}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "6px 10px",
  fontSize: 13,
  border: "1px solid #CBD5E1",
  borderRadius: 4,
  outline: "none",
  boxSizing: "border-box",
};

const previewBox: React.CSSProperties = {
  background: "var(--pn, #F8FAFC)",
  border: "1px solid #E2E8F0",
  borderRadius: 4,
  padding: 8,
  fontSize: 11,
  color: "#334155",
  whiteSpace: "pre-wrap",
  margin: 0,
  maxHeight: 200,
  overflowY: "auto",
};

const ghostBtn: React.CSSProperties = {
  padding: "6px 12px",
  fontSize: 12,
  background: "#fff",
  color: "#475569",
  border: "1px solid #CBD5E1",
  borderRadius: 4,
  cursor: "pointer",
};

const primaryBtn: React.CSSProperties = {
  padding: "6px 14px",
  fontSize: 12,
  background: "#16A34A",
  color: "#fff",
  border: "1px solid #16A34A",
  borderRadius: 4,
  cursor: "pointer",
  fontWeight: 600,
};
