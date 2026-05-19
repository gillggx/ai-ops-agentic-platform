"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

type DocRow = {
  id: number;
  // Java wire is snake_case (feedback_jackson_snake_case_wire.md)
  block_id: string;
  block_version: string;
  auto_generated: boolean;
  last_edited_by?: string | null;
  last_edited_at?: string | null;
};

export default function BlockDocsAdminPage() {
  const [rows, setRows] = useState<DocRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/block-docs");
        const body = await res.json();
        if (!res.ok) throw new Error(body?.message || `HTTP ${res.status}`);
        const list: DocRow[] = body?.data ?? body ?? [];
        setRows(list.sort((a, b) => (a.block_id || "").localeCompare(b.block_id || "")));
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <div style={{ padding: 24 }}>
      <h1 style={{ fontSize: 20, marginBottom: 4 }}>Block Documentation</h1>
      <p style={{ color: "#666", marginBottom: 16 }}>
        Markdown documentation per pipeline-builder block. Admin can edit; LLM
        reads these for catalog brief and inspect_block_doc. Rows marked
        auto-generated are LLM first drafts pending admin review.
      </p>
      {loading && <p>Loading...</p>}
      {err && <p style={{ color: "#c00" }}>Error: {err}</p>}
      {!loading && !err && (
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            fontSize: 14,
          }}
        >
          <thead>
            <tr style={{ borderBottom: "1px solid #ccc", textAlign: "left" }}>
              <th style={{ padding: "8px 12px" }}>Block</th>
              <th style={{ padding: "8px 12px" }}>Version</th>
              <th style={{ padding: "8px 12px" }}>Source</th>
              <th style={{ padding: "8px 12px" }}>Last Edited</th>
              <th style={{ padding: "8px 12px" }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} style={{ borderBottom: "1px solid #eee" }}>
                <td style={{ padding: "8px 12px", fontFamily: "monospace" }}>
                  {r.block_id}
                </td>
                <td style={{ padding: "8px 12px" }}>{r.block_version}</td>
                <td style={{ padding: "8px 12px" }}>
                  {r.auto_generated ? (
                    <span style={{ color: "#c70" }}>[auto-gen]</span>
                  ) : (
                    <span style={{ color: "#070" }}>[admin]</span>
                  )}
                </td>
                <td style={{ padding: "8px 12px", color: "#666" }}>
                  {r.last_edited_at
                    ? `${r.last_edited_by ?? "?"} @ ${new Date(
                        r.last_edited_at,
                      ).toLocaleString()}`
                    : "-"}
                </td>
                <td style={{ padding: "8px 12px" }}>
                  <Link
                    href={`/admin/block-docs/${r.block_id}/${r.block_version}`}
                    style={{ color: "#06f" }}
                  >
                    Edit
                  </Link>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={5} style={{ padding: 16, color: "#999" }}>
                  No block docs yet. Run
                  <code style={{ margin: "0 4px" }}>
                    tools/generate_block_docs.py
                  </code>
                  to seed.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
