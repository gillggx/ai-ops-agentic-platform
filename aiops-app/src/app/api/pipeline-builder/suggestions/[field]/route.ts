import { NextRequest, NextResponse } from "next/server";
import { BACKEND_BASE, authHeaders } from "../../_common";

export async function GET(_req: NextRequest, ctx: { params: Promise<{ field: string }> }) {
  const { field } = await ctx.params;
  const res = await fetch(`${BACKEND_BASE}/suggestions/${encodeURIComponent(field)}`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
