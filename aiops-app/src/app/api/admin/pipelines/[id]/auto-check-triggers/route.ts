import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  try {
    const res = await fetch(
      `${FASTAPI_BASE}/api/v1/pipelines/${id}/auto-check-triggers`,
      { headers: await authHeaders(), cache: "no-store" },
    );
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    console.error("[pipeline auto-check-triggers GET]", err);
    return NextResponse.json({ data: [] }, { status: 200 });
  }
}

/** PUT — replace the binding set on an active pipeline without going through
 *  the publish flow (which expects status='locked'). Body shape mirrors
 *  publish-auto-check: { event_types: [{event_type, match_filter?}] }. */
export async function PUT(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const body = await req.json();
  const headers = { ...(await authHeaders()), "Content-Type": "application/json" };
  const res = await fetch(
    `${FASTAPI_BASE}/api/v1/pipelines/${id}/auto-check-triggers`,
    { method: "PUT", headers, body: JSON.stringify(body) },
  );
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
