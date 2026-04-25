import { NextRequest, NextResponse } from "next/server";
import { BACKEND_BASE, authHeaders } from "../../../_common";

export async function POST(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const res = await fetch(`${BACKEND_BASE}/published-skills/${id}/retire`, {
    method: "POST",
    headers: await authHeaders(),
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
