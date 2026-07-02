import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";

export const dynamic = "force-dynamic";

// POST /api/agent-episodes/[key]/feedback -> Java /api/v1/agent-episodes/[key]/feedback
// Post-delivery feedback (符合 / 要修改 / 不是我要的) — the divergence signal
// for the Supervisor loop. Recording only; nothing fires automatically.
export async function POST(req: NextRequest, ctx: { params: Promise<{ key: string }> }) {
  const { key } = await ctx.params;
  const body = await req.json().catch(() => ({}));
  const res = await fetch(
    `${BASE}/api/v1/agent-episodes/${encodeURIComponent(key)}/feedback`,
    {
      method: "POST",
      headers: { ...(await authHeaders()), "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}
