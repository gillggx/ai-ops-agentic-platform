import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";
export const dynamic = "force-dynamic";

// Chat 草稿暫存區 (V78) — list / create / clear. Pure proxy to Java.
export async function GET() {
  const res = await fetch(`${BASE}/api/v1/chat-drafts`, {
    headers: await authHeaders(), cache: "no-store",
  });
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
}

export async function POST(req: NextRequest) {
  const body = await req.text();
  const res = await fetch(`${BASE}/api/v1/chat-drafts`, {
    method: "POST",
    headers: { ...(await authHeaders()), "Content-Type": "application/json" },
    body,
  });
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
}

export async function DELETE(req: NextRequest) {
  const keep = req.nextUrl.searchParams.get("keep_marked") ?? "true";
  const res = await fetch(`${BASE}/api/v1/chat-drafts?keep_marked=${encodeURIComponent(keep)}`, {
    method: "DELETE", headers: await authHeaders(), cache: "no-store",
  });
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
}
