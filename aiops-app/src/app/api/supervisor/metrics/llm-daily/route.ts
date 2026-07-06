import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";
export const dynamic = "force-dynamic";

/** GET /api/supervisor/metrics/llm-daily?days=7 → Java
 *  /api/v1/supervisor/metrics/llm-daily — per-day per-model LLM call stats
 *  [{ day, model, calls, empty_calls, error_calls, input_tokens,
 *     output_tokens, cache_read }]. */
export async function GET(req: NextRequest) {
  const days = req.nextUrl.searchParams.get("days");
  const qs = days ? `?days=${encodeURIComponent(days)}` : "";
  const res = await fetch(`${BASE}/api/v1/supervisor/metrics/llm-daily${qs}`, {
    headers: await authHeaders(), cache: "no-store",
  });
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
}
