import { NextRequest, NextResponse } from "next/server";
import { authHeaders as authHeadersFromSession } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

type Ctx = { params: Promise<{ block_id: string; block_version: string }> };

export async function GET(_req: NextRequest, { params }: Ctx) {
  const { block_id, block_version } = await params;
  const url = `${FASTAPI_BASE}/api/v1/block-docs/${block_id}/${block_version}`;
  const res = await fetch(url, {
    headers: await authHeadersFromSession(),
    cache: "no-store",
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}

export async function PUT(req: NextRequest, { params }: Ctx) {
  const { block_id, block_version } = await params;
  const body = await req.json();
  const url = `${FASTAPI_BASE}/api/v1/block-docs/${block_id}/${block_version}`;
  const res = await fetch(url, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      ...(await authHeadersFromSession()),
    },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
