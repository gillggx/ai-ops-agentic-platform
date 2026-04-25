# OIDC Multi-Provider Authentication Runbook

**Status**: 2026-04-25 — infrastructure deployed to prod. Credentials
(username/password) provider always on; OIDC providers activate per env var.

---

## Architecture

```
Browser ──► /login                                   (Next.js, public)
         ├─ Azure AD button?  → /api/auth/signin/microsoft-entra-id  ─► AAD
         ├─ Google button?    → /api/auth/signin/google              ─► Google
         ├─ Keycloak button?  → /api/auth/signin/keycloak            ─► KC
         ├─ Okta button?      → /api/auth/signin/okta                ─► Okta
         └─ Local form        → /api/auth/signin/credentials

IdP callback                   → /api/auth/callback/<provider>
                                  │
                                  ▼
              NextAuth signIn() callback
                                  │
                        POST /api/v1/auth/oidc-upsert
                        X-Upsert-Secret: <shared secret>
                                  │
                                  ▼ Java
                        match by (provider, sub) → link by email → create w/ ON_DUTY
                        issue Java JWT (30d expiry)
                                  │
                                  ▼
              stashed on NextAuth session.javaJwt
                                  │
                                  ▼
              /api/* proxies read session.javaJwt → Java as Bearer token
```

## Roles & menu visibility

| Role | Sees |
|---|---|
| `ON_DUTY` | Alarm Center, Dashboard |
| `PE` | Alarm Center, Dashboard, Pipeline Builder |
| `IT_ADMIN` | Everything + Users management |

Java RoleHierarchy: `IT_ADMIN > PE > ON_DUTY`. Admin role passes `hasRole('PE')` checks transparently.

First OIDC login → default role is **`ON_DUTY`**. IT_ADMIN must upgrade via `/admin/users`.

---

## Required env vars

### `/opt/aiops/aiops-app/.env.local`
```
# --- Always required ---
AUTH_SECRET=<openssl rand -base64 48>       # NextAuth cookie signing
NEXTAUTH_SECRET=<same value>                # alias for AUTH_SECRET
AIOPS_OIDC_UPSERT_SECRET=<openssl rand -base64 32>   # shared with Java
FASTAPI_BASE_URL=http://localhost:8002

# --- Optional OIDC providers — include ONLY those you want active ---
# Azure AD / Entra ID
OIDC_AZURE_CLIENT_ID=<app registration client id>
OIDC_AZURE_CLIENT_SECRET=<client secret>
OIDC_AZURE_TENANT_ID=<tenant id>            # or leave blank for "common"

# Google Workspace
OIDC_GOOGLE_CLIENT_ID=<oauth client id>.apps.googleusercontent.com
OIDC_GOOGLE_CLIENT_SECRET=<secret>

# Keycloak (self-hosted)
OIDC_KEYCLOAK_CLIENT_ID=aiops
OIDC_KEYCLOAK_CLIENT_SECRET=<secret>
OIDC_KEYCLOAK_ISSUER=https://keycloak.example.com/realms/aiops

# Okta / Auth0
OIDC_OKTA_CLIENT_ID=<client id>
OIDC_OKTA_CLIENT_SECRET=<secret>
OIDC_OKTA_ISSUER=https://<tenant>.okta.com

# --- Hard enforcement ---
# AIOPS_AUTH_REQUIRED=1       # when set, middleware redirects unauth to /login.
                              # Leave unset during gradual rollout.
```

### `/opt/aiops/java-backend/.env`
```
AIOPS_OIDC_UPSERT_SECRET=<same value as in aiops-app .env.local>
```

---

## IdP setup — per provider

### Azure AD (Entra ID)
1. Portal → Azure Active Directory → App registrations → **New registration**
2. Name: `AIOps Platform`
3. Supported account types: single tenant (or multi, depending on org policy)
4. Redirect URI (Web): `https://aiops-gill.com/api/auth/callback/microsoft-entra-id`
5. After creation → **Certificates & secrets** → New client secret → copy value
6. **Overview** → copy Application (client) ID + Directory (tenant) ID
7. Fill env vars, restart `aiops-app.service`

### Google
1. https://console.cloud.google.com → APIs & Services → OAuth consent screen → configure
2. Credentials → **Create OAuth client ID** → Web application
3. Authorized redirect URI: `https://aiops-gill.com/api/auth/callback/google`
4. Copy client id + secret → env vars → restart

### Keycloak
1. Create Realm (e.g. `aiops`)
2. Clients → Create client → `openid-connect` → `aiops`
3. Valid redirect URIs: `https://aiops-gill.com/api/auth/callback/keycloak`
4. Credentials tab → copy secret
5. Env: `OIDC_KEYCLOAK_ISSUER=https://<keycloak-host>/realms/aiops`

### Okta / Auth0
1. Create new OAuth 2.0 Application (Web / regular)
2. Login redirect URI: `https://aiops-gill.com/api/auth/callback/okta`
3. Copy client id + secret → env vars

---

## Verify

1. `curl -sk https://aiops-gill.com/api/auth/providers` — should list enabled providers
2. Visit `/login` — the provider buttons show, local form always present
3. Sign in via chosen provider → redirected back to `/` → session cookie set
4. DB check:
   ```sql
   SELECT id, username, email, roles, oidc_provider, last_login_at
   FROM users WHERE oidc_provider IS NOT NULL;
   ```
5. Menu visibility: new OIDC users land on ON_DUTY → see only Alarm Center + Dashboard

---

## Upgrade a user to PE / IT_ADMIN

1. Log in as existing IT_ADMIN (e.g. `admin` / `admin`)
2. Sidebar → `👥 Users`
3. Click the ☐ PE / ☐ IT_ADMIN chip → confirm reason (optional) → chip becomes ☑
4. The change is recorded in `role_change_logs`:
   ```sql
   SELECT * FROM role_change_logs ORDER BY changed_at DESC LIMIT 10;
   ```

---

## Rollback

If OIDC login is broken:
1. Remove OIDC_* env vars from `aiops-app/.env.local` (keep AUTH_SECRET).
   Login page will show ONLY local credentials form.
2. `sudo systemctl restart aiops-app.service`
3. Users still have DB accounts — local login with `admin` / your password works.

To fully disable OIDC + go back to shared-token mode:
1. Don't set `AIOPS_AUTH_REQUIRED`. Middleware won't redirect.
2. All `/api/*` proxies fall back to `INTERNAL_API_TOKEN` (shared admin).

---

## Gradual rollout suggestion

### Week 1 — shadow mode
- Configure one OIDC provider (e.g. Google) in env
- `AIOPS_AUTH_REQUIRED` stays UNSET
- Users can still access everything via shared-token mode
- Those who log in via OIDC get per-user session + role enforcement (menu)
- Validate first-login flow creates users correctly in DB

### Week 2 — enforce login
- Set `AIOPS_AUTH_REQUIRED=1` in aiops-app env
- Restart aiops-app
- All unauth requests now redirect to /login
- Still safe: shared token still works INSIDE proxies (so role enforcement
  is menu-only; a user typing URLs directly bypasses)

### Week 3 — proxy migration
- Migrate `/api/*` proxy routes to use `authHeaders()` from `lib/auth-proxy.ts`
- This makes Java see the ACTUAL user's JWT → server-side role enforcement
  engages on every call
- Per proxy migration: replace `Bearer ${TOKEN}` constants with `await authHeaders()`

---

## Known gaps / future work

- **Proxy migration not complete**: ~30 `/api/*` proxy routes still use
  shared `INTERNAL_API_TOKEN`. Until migrated, role checking is menu-filter
  only. Migration pattern is trivial — see `/api/admin/users-manage/*` for
  the template.
- **Token refresh**: NextAuth's session expires after default 30 days. We
  don't refresh the Java JWT mid-session; if Java's JWT (also 30d) expires
  first, subsequent proxy calls will 401 and user has to re-login.
- **Multi-IdP same-email users**: today one email = one users row. If the
  same person signs in via Azure AD one day and Google another day, and
  their email matches, they get the same row (with oidc_provider/sub of
  whichever came last). Not a bug but note the behaviour.
- **No user self-deactivation**: designed so — prevents accidental lockout.
  Ask IT_ADMIN to clean up stale OIDC accounts via `/admin/users`.
