/** Skills v2 — list (GET) / create (POST) */
import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";
export const dynamic = "force-dynamic";

export async function GET(_req: NextRequest) {
  const headers = await authHeaders();
  const res = await fetch(`${BASE}/api/v2/skills`, { headers, cache: "no-store" });
  return new Response(await res.text(), {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}

export async function POST(req: NextRequest) {
  const headers = await authHeaders();
  const body = await req.text();
  const res = await fetch(`${BASE}/api/v2/skills`, {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: body || "{}",
    cache: "no-store",
  });
  return new Response(await res.text(), {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}
