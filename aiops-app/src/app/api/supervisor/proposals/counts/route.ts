import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";
export const dynamic = "force-dynamic";

// GET /api/supervisor/proposals/counts -> Java { proposed, approved, rejected }
export async function GET() {
  const res = await fetch(`${BASE}/api/v1/supervisor/proposals/counts`, {
    headers: await authHeaders(), cache: "no-store",
  });
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
}
