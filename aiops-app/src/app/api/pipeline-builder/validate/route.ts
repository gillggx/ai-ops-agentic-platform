import { NextRequest, NextResponse } from "next/server";
import { BACKEND_BASE, authHeaders } from "../_common";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const res = await fetch(`${BACKEND_BASE}/validate`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify(body),
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
