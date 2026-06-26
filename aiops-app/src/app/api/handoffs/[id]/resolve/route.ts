import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";

export const dynamic = "force-dynamic";

// POST /api/handoffs/[id]/resolve -> Java POST /api/v1/handoffs/[id]/resolve
// This is where a dangerous action (delete/disable/activate) actually runs,
// under the logged-in user.
export async function POST(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const res = await fetch(`${BASE}/api/v1/handoffs/${encodeURIComponent(id)}/resolve`, {
    method: "POST",
    headers: { ...(await authHeaders()), "Content-Type": "application/json" },
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
