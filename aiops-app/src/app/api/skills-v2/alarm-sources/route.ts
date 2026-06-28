/** List of patrols that emit alarm — used by event-driven trigger picker. */
import { NextRequest } from "next/server";
import { authHeaders } from "@/lib/auth-proxy";

const BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const exclude = req.nextUrl.searchParams.get("excludeSlug") ?? "";
  const headers = await authHeaders();
  const url = new URL("/api/v2/skills/alarm-sources", BASE);
  if (exclude) url.searchParams.set("excludeSlug", exclude);
  const res = await fetch(url.toString(), { headers, cache: "no-store" });
  return new Response(await res.text(), {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
}
