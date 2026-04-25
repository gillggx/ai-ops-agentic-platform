/**
 * NextAuth v5 config — multi-provider OIDC + local credentials.
 *
 * Providers only register when the corresponding env vars are set. This means
 * the same build can be deployed to an env with just Azure AD (set OIDC_AZURE_*)
 * or just Keycloak (set OIDC_KEYCLOAK_*) or all four — no code changes.
 *
 * After a successful OIDC sign-in we call Java's /api/v1/auth/oidc-upsert
 * (protected by AIOPS_OIDC_UPSERT_SECRET shared secret) to materialise a
 * users row + get back a Java-issued JWT. We stash that JWT on the
 * NextAuth session so /api/* proxy routes can forward it to Java as
 * Authorization: Bearer.
 *
 * Credentials provider keeps local-password login working (fallback +
 * break-glass admin). It calls Java's /api/v1/auth/login directly.
 */

import type { NextAuthConfig } from "next-auth";
import NextAuth from "next-auth";
import AzureAd from "next-auth/providers/microsoft-entra-id";
import Google from "next-auth/providers/google";
import Keycloak from "next-auth/providers/keycloak";
import Okta from "next-auth/providers/okta";
import Credentials from "next-auth/providers/credentials";

const JAVA_BASE = process.env.FASTAPI_BASE_URL ?? "http://localhost:8002";
const UPSERT_SECRET = process.env.AIOPS_OIDC_UPSERT_SECRET ?? "";

interface JavaUserInfo {
  id: number;
  username: string;
  email?: string;
  roles: string[];
}

interface JavaAuthResponse {
  token_type: string;
  access_token: string;
  user: JavaUserInfo;
  created?: boolean;
}

async function javaOidcUpsert(args: {
  provider: string;
  sub: string;
  email?: string | null;
  name?: string | null;
}): Promise<JavaAuthResponse | null> {
  if (!UPSERT_SECRET) {
    console.warn("[auth] AIOPS_OIDC_UPSERT_SECRET not set — OIDC login will be rejected by Java");
    return null;
  }
  try {
    const res = await fetch(`${JAVA_BASE}/api/v1/auth/oidc-upsert`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Upsert-Secret": UPSERT_SECRET,
      },
      body: JSON.stringify({
        provider: args.provider,
        sub: args.sub,
        email: args.email ?? null,
        name: args.name ?? null,
      }),
      cache: "no-store",
    });
    if (!res.ok) {
      console.error("[auth] oidc-upsert failed", res.status, await res.text().catch(() => ""));
      return null;
    }
    const body = (await res.json()) as { data?: JavaAuthResponse } & JavaAuthResponse;
    return body.data ?? body;
  } catch (e) {
    console.error("[auth] oidc-upsert network error", e);
    return null;
  }
}

async function javaLocalLogin(username: string, password: string): Promise<JavaAuthResponse | null> {
  try {
    const res = await fetch(`${JAVA_BASE}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
      cache: "no-store",
    });
    if (!res.ok) return null;
    const body = (await res.json()) as { data?: JavaAuthResponse } & JavaAuthResponse;
    return body.data ?? body;
  } catch {
    return null;
  }
}

const providers: NextAuthConfig["providers"] = [];

// ── OIDC providers (only when env is set) ──────────────────────────────────
if (process.env.OIDC_AZURE_CLIENT_ID && process.env.OIDC_AZURE_CLIENT_SECRET) {
  providers.push(AzureAd({
    clientId: process.env.OIDC_AZURE_CLIENT_ID,
    clientSecret: process.env.OIDC_AZURE_CLIENT_SECRET,
    issuer: process.env.OIDC_AZURE_TENANT_ID
      ? `https://login.microsoftonline.com/${process.env.OIDC_AZURE_TENANT_ID}/v2.0`
      : undefined,
  }));
}
if (process.env.OIDC_GOOGLE_CLIENT_ID && process.env.OIDC_GOOGLE_CLIENT_SECRET) {
  providers.push(Google({
    clientId: process.env.OIDC_GOOGLE_CLIENT_ID,
    clientSecret: process.env.OIDC_GOOGLE_CLIENT_SECRET,
  }));
}
if (process.env.OIDC_KEYCLOAK_CLIENT_ID && process.env.OIDC_KEYCLOAK_ISSUER) {
  providers.push(Keycloak({
    clientId: process.env.OIDC_KEYCLOAK_CLIENT_ID,
    clientSecret: process.env.OIDC_KEYCLOAK_CLIENT_SECRET,
    issuer: process.env.OIDC_KEYCLOAK_ISSUER,
  }));
}
if (process.env.OIDC_OKTA_CLIENT_ID && process.env.OIDC_OKTA_ISSUER) {
  providers.push(Okta({
    clientId: process.env.OIDC_OKTA_CLIENT_ID,
    clientSecret: process.env.OIDC_OKTA_CLIENT_SECRET,
    issuer: process.env.OIDC_OKTA_ISSUER,
  }));
}

// ── Credentials (local username/password) — always enabled ────────────────
providers.push(
  Credentials({
    name: "Local",
    credentials: {
      username: { label: "Username", type: "text" },
      password: { label: "Password", type: "password" },
    },
    async authorize(creds) {
      if (!creds?.username || !creds?.password) return null;
      const resp = await javaLocalLogin(String(creds.username), String(creds.password));
      if (!resp) return null;
      return {
        id: String(resp.user.id),
        name: resp.user.username,
        email: resp.user.email,
        // NextAuth v5: everything on `user` flows into the jwt() callback below
        javaJwt: resp.access_token,
        roles: resp.user.roles,
        provider: "local",
      } as unknown as import("next-auth").User;
    },
  })
);

export const authConfig: NextAuthConfig = {
  providers,
  session: { strategy: "jwt" },
  pages: {
    signIn: "/login",
    error: "/login",
  },
  callbacks: {
    async signIn({ user, account, profile }) {
      if (account?.provider === "credentials") return true;  // authorize() already ran

      // OIDC path — exchange IdP identity for a Java JWT.
      const provider = account?.provider ?? "unknown";
      const sub = account?.providerAccountId || profile?.sub || user?.id;
      if (!sub) return false;
      const resp = await javaOidcUpsert({
        provider,
        sub: String(sub),
        email: user?.email ?? (profile as { email?: string })?.email ?? null,
        name: user?.name ?? (profile as { name?: string })?.name ?? null,
      });
      if (!resp) return false;
      // Stash the Java JWT + roles on the user object so jwt() callback can
      // persist them. NextAuth lets us mutate user here.
      (user as unknown as { javaJwt: string }).javaJwt = resp.access_token;
      (user as unknown as { roles: string[] }).roles = resp.user.roles;
      (user as unknown as { provider: string }).provider = provider;
      (user as unknown as { userId: number }).userId = resp.user.id;
      return true;
    },
    async jwt({ token, user }) {
      if (user) {
        const u = user as unknown as {
          javaJwt?: string; roles?: string[]; provider?: string; userId?: number;
        };
        if (u.javaJwt) token.javaJwt = u.javaJwt;
        if (u.roles) token.roles = u.roles;
        if (u.provider) token.provider = u.provider;
        if (u.userId) token.userId = u.userId;
      }
      return token;
    },
    async session({ session, token }) {
      const t = token as unknown as {
        javaJwt?: string; roles?: string[]; provider?: string; userId?: number;
      };
      (session as unknown as Record<string, unknown>).javaJwt = t.javaJwt;
      (session as unknown as Record<string, unknown>).roles = t.roles ?? [];
      (session as unknown as Record<string, unknown>).provider = t.provider;
      (session as unknown as Record<string, unknown>).userId = t.userId;
      return session;
    },
  },
  trustHost: true,
};

export const { handlers, auth, signIn, signOut } = NextAuth(authConfig);

/** Tell the /login page which provider buttons to show. */
export function availableProviders(): { id: string; label: string }[] {
  return providers
    .filter((p) => p && typeof p === "object" && "id" in p)
    .map((p) => {
      const obj = p as { id: string; name?: string };
      return { id: obj.id, label: obj.name || obj.id };
    });
}
