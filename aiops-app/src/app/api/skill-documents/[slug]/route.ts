import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";

export const dynamic = "force-dynamic";

async function proxy(req: NextRequest, slug: string, method: "GET" | "PUT" | "DELETE") {
  const headers = await authHeaders();
  const init: RequestInit = { method, headers, cache: "no-store" };
  if (method === "PUT") {
    init.body = await req.text();
    init.headers = { ...headers, "Content-Type": "application/json" };
  }
  const res = await fetch(`${BASE}/api/v1/skill-documents/${encodeURIComponent(slug)}`, init);
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ slug: string }> }) {
  const { slug } = await ctx.params;
  return proxy(req, slug, "GET");
}
export async function PUT(req: NextRequest, ctx: { params: Promise<{ slug: string }> }) {
  const { slug } = await ctx.params;
  return proxy(req, slug, "PUT");
}
export async function DELETE(req: NextRequest, ctx: { params: Promise<{ slug: string }> }) {
  const { slug } = await ctx.params;
  return proxy(req, slug, "DELETE");
}
