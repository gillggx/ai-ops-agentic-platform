import { NextRequest, NextResponse } from "next/server";
import { BACKEND_BASE, authHeaders } from "../_common";

export async function GET(req: NextRequest) {
  const includeRetired = req.nextUrl.searchParams.get("include_retired") === "true";
  const res = await fetch(
    `${BACKEND_BASE}/published-skills?include_retired=${includeRetired}`,
    { headers: await authHeaders() },
  );
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
