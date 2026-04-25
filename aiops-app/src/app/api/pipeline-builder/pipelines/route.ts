import { NextRequest, NextResponse } from "next/server";
import { BACKEND_BASE, authHeaders } from "../_common";

export async function GET(req: NextRequest) {
  const status = req.nextUrl.searchParams.get("status");
  const url = `${BACKEND_BASE}/pipelines${status ? `?status=${encodeURIComponent(status)}` : ""}`;
  const res = await fetch(url, { headers: await authHeaders(), cache: "no-store" });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const res = await fetch(`${BACKEND_BASE}/pipelines`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify(body),
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
