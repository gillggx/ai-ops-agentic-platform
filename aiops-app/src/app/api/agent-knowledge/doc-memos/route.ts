import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";
export const dynamic = "force-dynamic";

// Builder's doc sticky-notes (block_doc_memos) — read-only "Builder memory".
export async function GET() {
  const headers = await authHeaders();
  const res = await fetch(`${BASE}/api/v1/agent-knowledge/doc-memos`, { headers, cache: "no-store" });
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
}
