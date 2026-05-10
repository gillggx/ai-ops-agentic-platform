import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";
export const dynamic = "force-dynamic";

export async function GET() {
  const headers = await authHeaders();
  const res = await fetch(`${BASE}/api/v1/agent-examples`, { headers, cache: "no-store" });
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
}

export async function POST(req: NextRequest) {
  const body = await req.text();
  const headers = await authHeaders();
  const res = await fetch(`${BASE}/api/v1/agent-examples`, {
    method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body,
  });
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
}
