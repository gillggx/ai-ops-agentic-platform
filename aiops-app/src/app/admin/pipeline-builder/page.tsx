"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { deletePipeline, deprecatePipeline, listPipelines } from "@/lib/pipeline-builder/api";
import type { PipelineStatus, PipelineSummary } from "@/lib/pipeline-builder/types";
import StatusBadge from "@/components/pipeline-builder/StatusBadge";

const STATUS_FILTERS: Array<PipelineStatus | "all"> = [
  "all",
  "draft",
  "validating",
  "locked",
  "active",
  "archived",
];

// Phase 5-UX-7+ replaced "diagnostic" with "auto_check"; "skill" is the
// reusable on-demand pipeline kind. "diagnostic" kept only as a legacy
// fallback for pre-cutover rows whose pipeline_kind is null.
type KindFilter = "all" | "auto_patrol" | "auto_check" | "skill";

export default function PipelineBuilderListPage() {
  const [items, setItems] = useState<PipelineSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<PipelineStatus | "all">("all");
  const [kindFilter, setKindFilter] = useState<KindFilter>("all");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);

  // Treat legacy "diagnostic" kind rows as auto_check so they appear under
  // the new tab (and don't become invisible after the rename).
  const visibleItems = items.filter((p) => {
    if (kindFilter === "all") return true;
    const raw = p.pipeline_kind ?? "auto_check";
    const normalised = raw === "diagnostic" ? "auto_check" : raw;
    return normalised === kindFilter;
  });

  const load = async () => {
    setLoading(true);
    try {
      const rows = await listPipelines(filter === "all" ? undefined : filter);
      setItems(rows);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  return (
    <div style={{ padding: 24, fontFamily: "system-ui, sans-serif" }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 20 }}>
        <div>
          <h1 style={{ fontSize: 20, margin: 0, color: "#262626" }}>Pipeline Builder</h1>
          <div style={{ fontSize: 13, color: "#8c8c8c", marginTop: 4 }}>
            Visual DAG pipelines — 由積木組合而成的可重用資料處理流程
          </div>
        </div>
        <div style={{ marginLeft: "auto" }}>
          <Link
            href="/admin/pipeline-builder/new"
            style={{
              background: "#1890ff",
              color: "#fff",
              padding: "8px 16px",
              borderRadius: 4,
              textDecoration: "none",
              fontSize: 13,
              fontWeight: 500,
            }}
          >
            + 新建 Pipeline
          </Link>
        </div>
      </div>

      {/* Kind tabs — Auto Patrol / Auto-Check / Skill */}
      <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
        {(["all", "auto_patrol", "auto_check", "skill"] as KindFilter[]).map((k) => (
          <button
            key={k}
            onClick={() => setKindFilter(k)}
            style={{
              padding: "5px 14px",
              fontSize: 12,
              fontWeight: 600,
              borderRadius: 4,
              border: "1px solid",
              borderColor: kindFilter === k ? "#4F46E5" : "#CBD5E1",
              background: kindFilter === k ? "#EEF2FF" : "#fff",
              color: kindFilter === k ? "#3730A3" : "#475569",
              cursor: "pointer",
              letterSpacing: "0.02em",
            }}
          >
            {k === "all" ? "全部類型"
              : k === "auto_patrol" ? "🔍 Auto Patrol"
              : k === "auto_check" ? "🔬 Auto-Check"
              : "📚 Skill"}
          </button>
        ))}
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap" }}>
        {STATUS_FILTERS.map((s) => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            style={{
              padding: "5px 14px",
              fontSize: 12,
              borderRadius: 4,
              border: "1px solid",
              borderColor: filter === s ? "#1890ff" : "#d9d9d9",
              background: filter === s ? "#e6f7ff" : "#fff",
              color: filter === s ? "#0050b3" : "#595959",
              cursor: "pointer",
            }}
          >
            {s === "all" ? "全部" : s}
          </button>
        ))}
      </div>

      {error && (
        <div style={{ padding: 12, background: "#fff1f0", color: "#cf1322", borderRadius: 4, marginBottom: 12 }}>
          {error}
        </div>
      )}

      {selected.size > 0 && (
        <div style={{
          display: "flex", alignItems: "center", gap: 12,
          padding: "8px 14px", marginBottom: 10,
          background: "#fffbe6", border: "1px solid #ffe58f", borderRadius: 4,
          fontSize: 13,
        }}>
          <span style={{ color: "#ad6800" }}>已選 {selected.size} 條</span>
          <button
            disabled={busy}
            onClick={async () => {
              const ids = Array.from(selected);
              const eligible = items.filter((p) => ids.includes(p.id) && (p.status === "draft" || p.status === "archived"));
              if (eligible.length === 0) {
                alert("只能刪除 draft 或 archived 狀態的 pipeline");
                return;
              }
              if (!confirm(`確定刪除 ${eligible.length} 條 pipeline？此操作不可還原。`)) return;
              setBusy(true);
              const failures: string[] = [];
              for (const p of eligible) {
                try {
                  await deletePipeline(p.id);
                } catch (e) {
                  failures.push(`#${p.id}: ${(e as Error).message}`);
                }
              }
              setBusy(false);
              setSelected(new Set());
              if (failures.length > 0) alert(`部分失敗:\n${failures.join("\n")}`);
              load();
            }}
            style={{
              padding: "4px 12px", fontSize: 12,
              color: "#fff", background: "#cf1322",
              border: "1px solid #cf1322", borderRadius: 3,
              cursor: busy ? "not-allowed" : "pointer",
              opacity: busy ? 0.6 : 1,
            }}
          >
            🗑 刪除選取 ({selected.size})
          </button>
          <button
            onClick={() => setSelected(new Set())}
            style={{
              padding: "4px 12px", fontSize: 12,
              color: "#595959", background: "#fff",
              border: "1px solid #d9d9d9", borderRadius: 3,
              cursor: "pointer",
            }}
          >
            取消選取
          </button>
          <span style={{ marginLeft: "auto", color: "#8c8c8c", fontSize: 11 }}>
            僅 draft / archived 可刪除
          </span>
        </div>
      )}

      <div style={{ background: "#fff", border: "1px solid #e0e0e0", borderRadius: 6 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#fafafa" }}>
              <th style={{ ...th, width: 36 }}>
                <input
                  type="checkbox"
                  checked={visibleItems.length > 0 && visibleItems.every((p) => selected.has(p.id))}
                  onChange={(e) => {
                    if (e.target.checked) setSelected(new Set(visibleItems.map((p) => p.id)));
                    else setSelected(new Set());
                  }}
                />
              </th>
              <th style={th}>ID</th>
              <th style={th}>名稱</th>
              <th style={th}>狀態</th>
              <th style={th}>版本</th>
              <th style={th}>更新時間</th>
              <th style={th}>動作</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={7} style={{ padding: 40, textAlign: "center", color: "#8c8c8c" }}>
                  載入中...
                </td>
              </tr>
            )}
            {!loading && visibleItems.length === 0 && (
              <tr>
                <td colSpan={7} style={{ padding: 40, textAlign: "center", color: "#8c8c8c" }}>
                  尚無 pipeline，點右上「新建」建立第一條
                </td>
              </tr>
            )}
            {visibleItems.map((p) => (
              <tr key={p.id} style={{ borderTop: "1px solid #f0f0f0" }}>
                <td style={td}>
                  <input
                    type="checkbox"
                    checked={selected.has(p.id)}
                    onChange={(e) => {
                      const next = new Set(selected);
                      if (e.target.checked) next.add(p.id);
                      else next.delete(p.id);
                      setSelected(next);
                    }}
                  />
                </td>
                <td style={td}>{p.id}</td>
                <td style={td}>
                  <Link
                    href={`/admin/pipeline-builder/${p.id}`}
                    style={{ color: "#1890ff", textDecoration: "none" }}
                  >
                    {p.name}
                  </Link>
                  {/* Phase 4-A: surface migrated-from-skill lineage as a chip */}
                  {(() => {
                    const m = /skill #(\d+)/.exec(p.description || "");
                    return m ? (
                      <span
                        data-testid={`migrated-from-skill-${p.id}`}
                        title={`Auto-migrated from skill #${m[1]}`}
                        style={{
                          marginLeft: 8,
                          padding: "1px 7px",
                          fontSize: 10,
                          background: "#ebf8ff",
                          color: "#2c5282",
                          border: "1px solid #bee3f8",
                          borderRadius: 10,
                          letterSpacing: "0.03em",
                          fontWeight: 600,
                        }}
                      >
                        ↩ from skill #{m[1]}
                      </span>
                    ) : null;
                  })()}
                </td>
                <td style={td}>
                  <StatusBadge status={p.status} />
                </td>
                <td style={td}>{p.version}</td>
                <td style={td}>{p.updated_at ? new Date(p.updated_at).toLocaleString() : "—"}</td>
                <td style={td}>
                  <div style={{ display: "flex", gap: 6, flexWrap: "nowrap" }}>
                    {p.status !== "archived" && (
                      <button
                        onClick={async () => {
                          if (!confirm(`封存 pipeline #${p.id}？（封存後僅能 Clone 建立新版本）`)) return;
                          try {
                            await deprecatePipeline(p.id);
                            load();
                          } catch (e) {
                            alert((e as Error).message);
                          }
                        }}
                        style={{
                          padding: "3px 10px",
                          fontSize: 11,
                          color: "#cf1322",
                          background: "#fff1f0",
                          border: "1px solid #ffa39e",
                          borderRadius: 3,
                          cursor: "pointer",
                          whiteSpace: "nowrap",
                        }}
                      >
                        📦 Archive
                      </button>
                    )}
                    {(p.status === "draft" || p.status === "archived") && (
                      <button
                        disabled={busy}
                        onClick={async () => {
                          if (!confirm(`永久刪除 pipeline #${p.id}（${p.name}）？\n此操作不可還原。`)) return;
                          setBusy(true);
                          try {
                            await deletePipeline(p.id);
                            load();
                          } catch (e) {
                            alert((e as Error).message);
                          } finally {
                            setBusy(false);
                          }
                        }}
                        style={{
                          padding: "3px 10px",
                          fontSize: 11,
                          color: "#fff",
                          background: "#cf1322",
                          border: "1px solid #cf1322",
                          borderRadius: 3,
                          cursor: busy ? "not-allowed" : "pointer",
                          opacity: busy ? 0.6 : 1,
                          whiteSpace: "nowrap",
                        }}
                      >
                        🗑 刪除
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const th: React.CSSProperties = {
  padding: "10px 14px",
  textAlign: "left",
  color: "#595959",
  fontWeight: 600,
  fontSize: 12,
};

const td: React.CSSProperties = {
  padding: "10px 14px",
  color: "#262626",
};
