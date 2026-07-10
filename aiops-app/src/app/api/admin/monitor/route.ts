import { authHeaders } from "@/lib/auth-proxy";

// /system/monitor page data — proxies Java's path-parity alias.
// 2026-07-10 fix: was sending the legacy INTERNAL_API_TOKEN as Bearer (Java
// /api/v1 expects the user's JWT → rejected → page broke) and defaulted to
// :8000 (the frontend itself). Use the session JWT like every other proxy.
const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";

export async function GET() {
  const headers = await authHeaders();
  const res = await fetch(`${FASTAPI_BASE}/api/v1/system/monitor`, {
    headers, cache: "no-store",
  });
  return new Response(await res.text(), {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}
