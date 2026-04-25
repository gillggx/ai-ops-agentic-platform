/**
 * Shared helpers for /api/pipeline-builder/* proxy routes.
 *
 * 2026-04-25 migrated from sync INTERNAL_API_TOKEN-only to async session-aware
 * headers via `lib/auth-proxy`. Every caller must `await authHeaders()`.
 */

import { authHeaders as authHeadersFromSession } from "@/lib/auth-proxy";

const FASTAPI_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8000";

export const BACKEND_BASE = `${FASTAPI_BASE}/api/v1/pipeline-builder`;

/**
 * Returns the best-available Authorization header — session JWT if logged in,
 * else falls back to INTERNAL_API_TOKEN (legacy shared-token mode).
 *
 * Always await it:
 *   const res = await fetch(url, { headers: await authHeaders() });
 */
export async function authHeaders(
  extra: Record<string, string> = {},
): Promise<Record<string, string>> {
  return authHeadersFromSession(extra);
}
