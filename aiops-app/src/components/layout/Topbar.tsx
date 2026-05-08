"use client";

import { useState } from "react";
import { useSession, signOut } from "next-auth/react";
import { NotificationBell } from "./NotificationBell";

const ROLE_COLORS: Record<string, { bg: string; color: string }> = {
  IT_ADMIN: { bg: "#fef2f2", color: "#991b1b" },
  PE:       { bg: "#eff6ff", color: "#1e40af" },
  ON_DUTY:  { bg: "#f0fdf4", color: "#166534" },
};

export function Topbar() {
  const { data: session } = useSession();
  return (
    <header style={{
      height: 48,
      background: "#ffffff",
      borderBottom: "1px solid #e2e8f0",
      display: "flex",
      alignItems: "center",
      padding: "0 var(--sp-xl)",
      flexShrink: 0,
      position: "sticky",
      top: 0,
      zIndex: 100,
      gap: 10,
    }}>
      <span style={{ fontWeight: 700, fontSize: "var(--fs-xl)", color: "#2b6cb0", letterSpacing: "-0.3px" }}>
        AIOps
      </span>
      <div style={{ flex: 1 }} />
      {session && <NotificationBell />}
      <UserMenu />
    </header>
  );
}

function UserMenu() {
  const { data: session, status } = useSession();
  const [open, setOpen] = useState(false);

  if (status === "loading") {
    return <div style={{ fontSize: 12, color: "#94a3b8" }}>…</div>;
  }

  // Not logged in (legacy shared-token mode) — show a subtle "Sign in" link.
  if (!session) {
    return (
      <a href="/login" style={{
        fontSize: 13, color: "#64748b", textDecoration: "none",
        padding: "6px 12px", borderRadius: 6,
        border: "1px solid #e2e8f0",
      }}>
        登入
      </a>
    );
  }

  const roles = (session as unknown as { roles?: string[] }).roles ?? [];
  const provider = (session as unknown as { provider?: string }).provider ?? "local";
  const username = session.user?.name ?? session.user?.email ?? "user";

  // Prefer highest role for display (IT_ADMIN > PE > ON_DUTY)
  const topRole =
    roles.includes("IT_ADMIN") ? "IT_ADMIN" :
    roles.includes("PE") ? "PE" :
    roles.includes("ON_DUTY") ? "ON_DUTY" : null;

  return (
    <div style={{ position: "relative" }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "6px 12px", borderRadius: 6,
          border: "1px solid #e2e8f0", background: "#fff",
          cursor: "pointer", fontSize: 13, color: "#1a202c",
        }}
      >
        <span style={avatarStyle}>
          {username.slice(0, 1).toUpperCase()}
        </span>
        <span style={{ fontWeight: 600 }}>{username}</span>
        {topRole && (
          <span style={{
            padding: "2px 7px", borderRadius: 10, fontSize: 10, fontWeight: 700,
            background: ROLE_COLORS[topRole]?.bg ?? "#f1f5f9",
            color: ROLE_COLORS[topRole]?.color ?? "#475569",
          }}>
            {topRole}
          </span>
        )}
        <span style={{ fontSize: 10, color: "#94a3b8" }}>▾</span>
      </button>

      {open && (
        <>
          {/* Click-away overlay */}
          <div
            onClick={() => setOpen(false)}
            style={{ position: "fixed", inset: 0, zIndex: 99 }}
          />
          <div style={dropdownStyle}>
            <div style={{ padding: "10px 14px", borderBottom: "1px solid #f1f5f9" }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#0f172a" }}>{username}</div>
              {session.user?.email && (
                <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>{session.user.email}</div>
              )}
              <div style={{ display: "flex", gap: 4, marginTop: 6, flexWrap: "wrap" }}>
                {roles.map(r => (
                  <span key={r} style={{
                    padding: "1px 6px", borderRadius: 3, fontSize: 10, fontWeight: 600,
                    background: ROLE_COLORS[r]?.bg ?? "#f1f5f9",
                    color: ROLE_COLORS[r]?.color ?? "#475569",
                  }}>{r}</span>
                ))}
              </div>
              <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 4 }}>
                登入方式：{provider}
              </div>
            </div>

            <DropdownLink href="/me/profile" icon="⚙️" label="帳號設定" onClick={() => setOpen(false)} />
            <DropdownLink href="/me/change-password" icon="🔑" label="變更密碼" onClick={() => setOpen(false)} />
            <DropdownLink href="/me/memories" icon="🧠" label="我的記憶" onClick={() => setOpen(false)} />

            <div style={{ borderTop: "1px solid #f1f5f9" }} />

            <button
              onClick={() => signOut({ callbackUrl: "/login" })}
              style={{
                width: "100%", padding: "10px 14px",
                background: "#fff", border: "none", cursor: "pointer",
                fontSize: 13, color: "#dc2626", textAlign: "left",
                fontWeight: 600,
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "#fef2f2")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "#fff")}
            >
              🚪 登出
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function DropdownLink({ href, icon, label, onClick }: {
  href: string; icon: string; label: string; onClick: () => void;
}) {
  return (
    <a
      href={href}
      onClick={onClick}
      style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: "9px 14px",
        textDecoration: "none", color: "#374151",
        fontSize: 13, fontWeight: 500,
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = "#f8fafc")}
      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
    >
      <span style={{ fontSize: 14 }}>{icon}</span>
      <span>{label}</span>
    </a>
  );
}

const avatarStyle: React.CSSProperties = {
  width: 24, height: 24, borderRadius: "50%",
  background: "#2b6cb0", color: "#fff",
  display: "flex", alignItems: "center", justifyContent: "center",
  fontSize: 11, fontWeight: 700,
};

const dropdownStyle: React.CSSProperties = {
  position: "absolute",
  top: "calc(100% + 4px)",
  right: 0,
  zIndex: 100,
  minWidth: 220,
  background: "#fff",
  border: "1px solid #e2e8f0",
  borderRadius: 6,
  boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
  overflow: "hidden",
};
