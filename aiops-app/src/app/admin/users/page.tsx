"use client";

import { useCallback, useEffect, useState } from "react";

type Role = "IT_ADMIN" | "PE" | "ON_DUTY";
const ALL_ROLES: Role[] = ["IT_ADMIN", "PE", "ON_DUTY"];

interface User {
  id: number;
  username: string;
  email: string;
  roles: Role[];
  isActive: boolean;
  oidcProvider: string | null;
  lastLoginAt: string | null;
}

export default function UsersAdminPage() {
  const [users, setUsers] = useState<User[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/users-manage", { cache: "no-store" });
      if (!res.ok) throw new Error(`${res.status}`);
      const body = await res.json();
      setUsers(Array.isArray(body) ? body : body.data ?? []);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function updateRoles(userId: number, nextRoles: Role[]) {
    if (nextRoles.length === 0) { alert("至少要保留一個 role"); return; }
    const reason = window.prompt("變更原因（選填）") ?? "";
    setBusyId(userId);
    try {
      const res = await fetch(`/api/admin/users-manage/${userId}/roles`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ roles: nextRoles, reason }),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(text.slice(0, 200) || `${res.status}`);
      }
      await load();
    } catch (e) {
      alert(`變更失敗：${(e as Error).message}`);
    } finally {
      setBusyId(null);
    }
  }

  async function toggleActive(userId: number, nextActive: boolean) {
    setBusyId(userId);
    try {
      const res = await fetch(`/api/admin/users-manage/${userId}/active`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ isActive: nextActive }),
      });
      if (!res.ok) throw new Error(`${res.status}`);
      await load();
    } catch (e) {
      alert(`變更失敗：${(e as Error).message}`);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div style={{ padding: 24, maxWidth: 1200, fontFamily: "system-ui, sans-serif" }}>
      <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: "#1a202c" }}>
        👥 使用者權限管理
      </h1>
      <p style={{ fontSize: 13, color: "#64748b", marginTop: 4, marginBottom: 20 }}>
        IT_ADMIN ＞ PE ＞ ON_DUTY（角色層級繼承：IT_ADMIN 自動擁有 PE 與 ON_DUTY 權限）。
        新建立的 OIDC 使用者預設為 <strong>ON_DUTY</strong>，需由管理員手動升級。
      </p>

      {error && (
        <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", color: "#991b1b",
                      padding: 10, borderRadius: 6, fontSize: 13, marginBottom: 12 }}>
          載入失敗：{error}
        </div>
      )}

      {users === null && !error ? (
        <div style={{ color: "#94a3b8", fontSize: 13 }}>載入中…</div>
      ) : users && users.length === 0 ? (
        <div style={{ padding: 32, textAlign: "center", color: "#94a3b8" }}>無使用者</div>
      ) : users ? (
        <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 8, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: "#f8fafc", borderBottom: "1px solid #e2e8f0" }}>
                <th style={th}>ID</th>
                <th style={th}>使用者</th>
                <th style={th}>Email</th>
                <th style={th}>Provider</th>
                <th style={th}>角色</th>
                <th style={th}>狀態</th>
                <th style={{ ...th, textAlign: "right" }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u, i) => (
                <tr key={u.id} style={{ background: i % 2 ? "#fafafa" : "#fff", borderBottom: "1px solid #f0f0f0" }}>
                  <td style={td}>{u.id}</td>
                  <td style={{ ...td, fontWeight: 600 }}>{u.username}</td>
                  <td style={{ ...td, color: "#64748b" }}>{u.email}</td>
                  <td style={td}>
                    {u.oidcProvider ? (
                      <span style={providerChip}>{u.oidcProvider}</span>
                    ) : (
                      <span style={{ color: "#94a3b8", fontSize: 11 }}>local</span>
                    )}
                  </td>
                  <td style={td}>
                    <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                      {ALL_ROLES.map((r) => {
                        const has = u.roles.includes(r);
                        return (
                          <button
                            key={r}
                            type="button"
                            disabled={busyId === u.id}
                            onClick={() => {
                              const next = has ? u.roles.filter((x) => x !== r) : [...u.roles, r];
                              void updateRoles(u.id, next);
                            }}
                            style={{
                              padding: "3px 10px",
                              borderRadius: 4,
                              border: `1px solid ${has ? ROLE_COLORS[r].border : "#e2e8f0"}`,
                              background: has ? ROLE_COLORS[r].bg : "#fff",
                              color: has ? ROLE_COLORS[r].color : "#94a3b8",
                              fontSize: 11, fontWeight: 600, cursor: "pointer",
                            }}
                            title={has ? `點擊移除 ${r}` : `點擊賦予 ${r}`}
                          >
                            {has ? "☑" : "☐"} {r}
                          </button>
                        );
                      })}
                    </div>
                  </td>
                  <td style={td}>
                    <span style={{
                      padding: "2px 8px", borderRadius: 10, fontSize: 11, fontWeight: 600,
                      background: u.isActive ? "#dcfce7" : "#fee2e2",
                      color: u.isActive ? "#166534" : "#991b1b",
                    }}>
                      {u.isActive ? "active" : "disabled"}
                    </span>
                  </td>
                  <td style={{ ...td, textAlign: "right" }}>
                    <button
                      type="button"
                      disabled={busyId === u.id}
                      onClick={() => void toggleActive(u.id, !u.isActive)}
                      style={{
                        padding: "4px 10px", fontSize: 11, borderRadius: 4,
                        border: "1px solid #d4d4d8",
                        background: "#fff", color: "#475569",
                        cursor: busyId === u.id ? "wait" : "pointer",
                      }}
                    >
                      {u.isActive ? "停用" : "啟用"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

const th: React.CSSProperties = {
  padding: "8px 12px", textAlign: "left", fontSize: 11,
  fontWeight: 700, color: "#4a5568", textTransform: "uppercase", letterSpacing: "0.3px",
};
const td: React.CSSProperties = { padding: "8px 12px", verticalAlign: "middle" };
const providerChip: React.CSSProperties = {
  padding: "2px 8px", borderRadius: 10, background: "#f5f3ff",
  color: "#5b21b6", fontSize: 10, fontWeight: 600,
};

const ROLE_COLORS: Record<Role, { bg: string; color: string; border: string }> = {
  IT_ADMIN: { bg: "#fef2f2", color: "#991b1b", border: "#ef4444" },
  PE:       { bg: "#eff6ff", color: "#1e40af", border: "#3b82f6" },
  ON_DUTY:  { bg: "#f0fdf4", color: "#166534", border: "#10b981" },
};
