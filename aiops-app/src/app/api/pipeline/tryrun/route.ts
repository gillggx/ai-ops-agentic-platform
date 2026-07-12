/** My Drafts (2026-07-12) — 草稿卡 Try Run：跑一次回瘦身結果（圖卡+節點摘要）。 */
import { NextResponse, type NextRequest } from "next/server";
import { getBearerToken } from "@/lib/auth-proxy";

const SIDECAR_BASE = process.env.SIDECAR_BASE_URL ?? "http://127.0.0.1:8050";
const SIDECAR_TOKEN = process.env.SIDECAR_SERVICE_TOKEN ?? "";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

export async function POST(req: NextRequest) {
  const authCtx = await getBearerToken();
  if (authCtx.source !== "session") {
    return NextResponse.json({ error: "login required" }, { status: 401 });
  }
  let body: { pipeline_json?: unknown; inputs?: unknown };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON" }, { status: 400 });
  }
  if (!body.pipeline_json || typeof body.pipeline_json !== "object") {
    return NextResponse.json({ error: "pipeline_json required" }, { status: 400 });
  }
  try {
    const res = await fetch(`${SIDECAR_BASE}/internal/pipeline/tryrun`, {
      method: "POST",
      headers: {
        "X-Service-Token": SIDECAR_TOKEN,
        "X-User-Id": String(authCtx.userId ?? 0),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ pipeline_json: body.pipeline_json, inputs: body.inputs ?? {} }),
      cache: "no-store",
    });
    return new NextResponse(await res.text(), {
      status: res.status, headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 502 });
  }
}
