/**
 * Proxy route — forwards GET /api/admin/patrol-activity to Java
 * /api/v1/patrol-activity, strips the ApiResponse envelope so the client
 * page receives the data directly.
 *
 * Query params pass through unchanged (snake_case on the wire — see
 * feedback_jackson_snake_case_wire).
 */

import { NextRequest, NextResponse } from "next/server";
import { INTERNAL_API_TOKEN as INTERNAL_TOKEN } from "@/lib/internal-token";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

export async function GET(req: NextRequest): Promise<Response> {
  const url = new URL("/api/v1/patrol-activity", FASTAPI_BASE);
  req.nextUrl.searchParams.forEach((v, k) => url.searchParams.set(k, v));

  const upstream = await fetch(url.toString(), {
    method: "GET",
    headers: {
      "Authorization": `Bearer ${INTERNAL_TOKEN}`,
    },
    cache: "no-store",
  });

  const envelope = await upstream.json().catch(() => ({}));
  // Java wraps responses in { data: ... }; unwrap so the client doesn't
  // need to know about the envelope shape.
  const payload = envelope?.data ?? envelope;
  return NextResponse.json(payload, { status: upstream.status });
}
