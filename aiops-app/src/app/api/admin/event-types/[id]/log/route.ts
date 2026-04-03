import { NextRequest, NextResponse } from "next/server";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";
const TOKEN = process.env.INTERNAL_API_TOKEN ?? "dev-token";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const limit = req.nextUrl.searchParams.get("limit") ?? "20";

  const res = await fetch(
    `${FASTAPI_BASE}/api/v1/event-types/${encodeURIComponent(id)}/log?limit=${limit}`,
    { headers: { Authorization: `Bearer ${TOKEN}` }, cache: "no-store" }
  );
  const json = await res.json();
  return NextResponse.json(json.data ?? json);
}
