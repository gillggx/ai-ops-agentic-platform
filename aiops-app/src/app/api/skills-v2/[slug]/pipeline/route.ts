/** 真 Skill 化 F4 — 參數化精靈更新出口（pipeline_json / doc）。 */
import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";
export const dynamic = "force-dynamic";

/** 參數化 (2026-07-10): 啟用表單要掃候選 — 取 skill + 綁定的 pipeline_json。 */
export async function GET(_req: NextRequest, ctx: { params: Promise<{ slug: string }> }) {
  const { slug } = await ctx.params;
  const res = await fetch(`${BASE}/api/v2/skills/${encodeURIComponent(slug)}/full`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  return new Response(await res.text(), {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}

export async function PUT(req: NextRequest, ctx: { params: Promise<{ slug: string }> }) {
  const { slug } = await ctx.params;
  const body = await req.text();
  const res = await fetch(`${BASE}/api/v2/skills/${encodeURIComponent(slug)}/pipeline`, {
    method: "PUT",
    headers: { ...(await authHeaders()), "Content-Type": "application/json" },
    body: body || "{}",
    cache: "no-store",
  });
  return new Response(await res.text(), {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}
