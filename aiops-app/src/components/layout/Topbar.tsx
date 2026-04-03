"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

export function Topbar() {
  const pathname = usePathname();
  const [alarmBadge, setAlarmBadge] = useState(0);

  useEffect(() => {
    async function fetchBadge() {
      try {
        const res = await fetch("/api/admin/alarms/stats");
        if (!res.ok) return;
        const d = await res.json();
        // Show badge for CRITICAL + HIGH only (actionable)
        setAlarmBadge((d.critical ?? 0) + (d.high ?? 0));
      } catch { /* ignore */ }
    }
    fetchBadge();
    const id = setInterval(fetchBadge, 30000);
    return () => clearInterval(id);
  }, []);

  return (
    <header style={{
      height: 48,
      background: "#ffffff",
      borderBottom: "1px solid #e2e8f0",
      display: "flex",
      alignItems: "center",
      padding: "0 20px",
      gap: 24,
      flexShrink: 0,
      position: "sticky",
      top: 0,
      zIndex: 100,
    }}>
      {/* Brand */}
      <span style={{ fontWeight: 700, fontSize: 15, color: "#2b6cb0", letterSpacing: "-0.3px" }}>
        AIOps
      </span>

      {/* Nav */}
      <nav style={{ display: "flex", gap: 4 }}>
        {[
          { href: "/",             label: "Operations Center", badge: alarmBadge },
          { href: "/admin/skills", label: "Knowledge Studio",  badge: 0 },
          { href: "/system",       label: "System Admin",      badge: 0 },
        ].map((item) => {
          const base = item.href === "/admin/skills" ? "/admin" : item.href;
          const active = pathname === item.href
            || (base !== "/" && pathname.startsWith(base));
          return (
            <Link key={item.href} href={item.href} style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "4px 12px", borderRadius: 6,
              fontSize: 13,
              fontWeight: active ? 600 : 400,
              color: active ? "#2b6cb0" : "#718096",
              background: active ? "#ebf4ff" : "transparent",
              textDecoration: "none",
              transition: "background 0.15s",
            }}>
              {item.label}
              {item.badge > 0 && (
                <span style={{
                  background: "#e53e3e", color: "#fff",
                  fontSize: 10, fontWeight: 700,
                  padding: "1px 5px", borderRadius: 8, lineHeight: 1.4,
                }}>
                  {item.badge}
                </span>
              )}
            </Link>
          );
        })}
      </nav>
    </header>
  );
}
