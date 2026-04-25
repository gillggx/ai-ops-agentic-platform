import { NextRequest, NextResponse } from "next/server";
import { BACKEND_BASE, authHeaders } from "../../_common";

/** Phase 4-A: proxy POST /pipeline-builder/migrate/skill/{id}?dry_run=(true|false) */
export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const dryRun = req.nextUrl.searchParams.get("dry_run") ?? "true";
  const url = `${BACKEND_BASE}/migrate/skill/${encodeURIComponent(id)}?dry_run=${dryRun}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { ...(await authHeaders()), "Content-Type": "application/json" },
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
