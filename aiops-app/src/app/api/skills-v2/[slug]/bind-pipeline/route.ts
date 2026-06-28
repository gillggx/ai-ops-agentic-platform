/** Bind a pb_pipeline to a skill_v2 row. Called from PB auto-bind hook. */
import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest, ctx: { params: Promise<{ slug: string }> }) {
  const { slug } = await ctx.params;
  const headers = await authHeaders();
  const body = await req.text();
  const res = await fetch(
    `${BASE}/api/v2/skills/${encodeURIComponent(slug)}/bind-pipeline`,
    {
      method: "POST",
      headers: { ...headers, "Content-Type": "application/json" },
      body: body || "{}",
      cache: "no-store",
    },
  );
  return new Response(await res.text(), {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}
