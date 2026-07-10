/**
 * Skill 參數化 (2026-07-10) — proxy to sidecar /internal/pipeline/parameterize.
 *
 * POST {pipeline_json}                → {candidates: [...]}        (scan only)
 * POST {pipeline_json, accept: [...]} → {pipeline_json, inputs}    (apply)
 *
 * Deterministic transform, no persistence — the actual skill writes still go
 * through the Java JWT-guarded /api/skills-v2/* routes. Requires a logged-in
 * session so the sidecar service token is never reachable anonymously.
 */
import { NextResponse, type NextRequest } from "next/server";
import { getBearerToken } from "@/lib/auth-proxy";

const SIDECAR_BASE = process.env.SIDECAR_BASE_URL ?? "http://127.0.0.1:8050";
const SIDECAR_TOKEN = process.env.SIDECAR_SERVICE_TOKEN ?? "";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const authCtx = await getBearerToken();
  if (authCtx.source !== "session") {
    return NextResponse.json({ error: "login required" }, { status: 401 });
  }
  if (!SIDECAR_TOKEN) {
    return NextResponse.json({ error: "SIDECAR_SERVICE_TOKEN not configured" }, { status: 503 });
  }
  let body: { pipeline_json?: unknown; accept?: unknown };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON" }, { status: 400 });
  }
  if (!body.pipeline_json || typeof body.pipeline_json !== "object") {
    return NextResponse.json({ error: "pipeline_json required" }, { status: 400 });
  }
  try {
    const res = await fetch(`${SIDECAR_BASE}/internal/pipeline/parameterize`, {
      method: "POST",
      headers: {
        "X-Service-Token": SIDECAR_TOKEN,
        "X-User-Id": String(authCtx.userId ?? 0),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        pipeline_json: body.pipeline_json,
        accept: Array.isArray(body.accept) ? body.accept : undefined,
      }),
      cache: "no-store",
    });
    return new NextResponse(await res.text(), {
      status: res.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
