import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";
export const dynamic = "force-dynamic";

export async function PATCH(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await req.text();
  const headers = await authHeaders();
  const res = await fetch(`${BASE}/api/v1/agent-examples/${id}`, {
    method: "PATCH", headers: { ...headers, "Content-Type": "application/json" }, body,
  });
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
}

export async function DELETE(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const headers = await authHeaders();
  const res = await fetch(`${BASE}/api/v1/agent-examples/${id}`, { method: "DELETE", headers });
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
}
