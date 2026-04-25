import { NextRequest, NextResponse } from "next/server";
import { BACKEND_BASE, authHeaders } from "../_common";

export async function GET(req: NextRequest) {
  const category = req.nextUrl.searchParams.get("category");
  const url = `${BACKEND_BASE}/blocks${category ? `?category=${encodeURIComponent(category)}` : ""}`;
  const res = await fetch(url, { headers: await authHeaders(), cache: "no-store" });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
