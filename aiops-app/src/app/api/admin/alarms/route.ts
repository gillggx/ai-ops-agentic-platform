import { NextRequest, NextResponse } from "next/server";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";
const TOKEN = process.env.INTERNAL_API_TOKEN ?? "";

function authHeaders() {
  return { "Authorization": `Bearer ${TOKEN}` };
}

export async function GET(req: NextRequest) {
  const params = req.nextUrl.searchParams.toString();
  const url = `${FASTAPI_BASE}/api/v1/alarms${params ? `?${params}` : ""}`;
  const res = await fetch(url, { headers: authHeaders() });
  const data = await res.json();
  if (!res.ok) return NextResponse.json({ error: data.message ?? "Failed" }, { status: res.status });
  return NextResponse.json(data.data ?? []);
}
