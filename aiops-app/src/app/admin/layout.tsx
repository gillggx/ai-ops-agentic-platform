"use client";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ padding: 32, color: "#1a202c", height: "100%", overflowY: "auto" }}>
      {children}
    </div>
  );
}
