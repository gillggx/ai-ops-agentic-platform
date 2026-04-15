"use client";

export function Topbar() {
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
    }}>
      <span style={{ fontWeight: 700, fontSize: "var(--fs-xl)", color: "#2b6cb0", letterSpacing: "-0.3px" }}>
        AIOps
      </span>
    </header>
  );
}
