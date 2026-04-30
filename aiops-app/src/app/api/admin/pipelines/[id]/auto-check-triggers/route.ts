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
