/** Raw simulator event types — used by event-driven trigger picker (raw-event mode). */
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";
export const dynamic = "force-dynamic";

export async function GET() {
  const headers = await authHeaders();
  const url = new URL("/api/v2/skills/event-types", BASE);
  const res = await fetch(url.toString(), { headers, cache: "no-store" });
  return new Response(await res.text(), {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}
