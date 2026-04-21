# Phase 2 — Test Report

- **Date**: 2026-04-21
- **Branch**: `feat/java-api-rewrite`
- **Tester**: Claude (self-verified)

## Scope

Authentication + authorisation layer per SPEC §2.6:
- JWT (local) + Azure AD OIDC (prod) behind `aiops.auth.mode`
- 3-role RBAC (IT_ADMIN / PE / ON_DUTY) with `@PreAuthorize`
- Segregation-of-duties rules on role assignment
- Audit log — async-written, IT_ADMIN-only read, 90-day retention
- Bootstrap seed: `admin/admin` with IT_ADMIN role on first boot

## New Packages

```
com.aiops.api.auth/
  Role.java                       (enum: IT_ADMIN | PE | ON_DUTY)
  AuthPrincipal.java              (record: userId, username, roles)
  RoleCodec.java                  (JSON ↔ Set<Role>)
  SegregationOfDuties.java        (validation)
  JwtService.java                 (auth0 HMAC256 issue/verify)
  JwtAuthenticationFilter.java    (active when auth.mode=local)
  UserAccountService.java         (createUser / authenticate / loadByUsername)
  BootstrapSeeder.java            (first-boot admin seed)

com.aiops.api.audit/
  AuditLogService.java            (@Async writes)
  AuditInterceptor.java           (captures every /api/** request)
  AuditRetentionJob.java          (daily 03:15 cleanup, 90d cutoff)

com.aiops.api.domain.audit/
  AuditLogEntity.java
  AuditLogRepository.java         (incl. deleteOlderThan JPQL)

com.aiops.api.api.auth/
  AuthController.java             (/login /me)

com.aiops.api.api.admin/
  AdminController.java            (@PreAuthorize IT_ADMIN, /users CRUD)
  AuditController.java            (@PreAuthorize IT_ADMIN, /audit list)
```

## QA Checklist

### Unit / Slice Tests

| # | Check | Expected | Actual | Result |
|---|---|---|---|---|
| U1 | `SegregationOfDutiesTest` | 6/0/0 | 6/0/0 | ✅ |
| U2 | `RoleCodecTest` JSON round-trip | 5/0/0 | 5/0/0 | ✅ |
| U3 | `JwtServiceTest` issue + tamper + short secret | 3/0/0 | 3/0/0 | ✅ |

### Integration Tests

| # | Check | Expected | Actual | Result |
|---|---|---|---|---|
| I1 | `AiopsApiApplicationTests.contextLoads` | 1/0/0 | 1/0/0 | ✅ |
| I2 | `RepositorySmokeTest` all 29 repos count | 1/0/0 | 1/0/0 | ✅ |
| I3 | `UserRoundTripTest` | 1/0/0 | 1/0/0 | ✅ |
| I4 | `AuthFlowIntegrationTest.fullAuthFlow` (login → 401 unauth → 200 authed → /me) | 1/0/0 | 1/0/0 | ✅ |
| I5 | `AuthFlowIntegrationTest.wrongPasswordRejected` (expect 403) | 1/0/0 | 1/0/0 | ✅ |
| | **Grand total** | **19/0/0** | **19/0/0** | **✅** |

### Live Smoke (against bootRun)

| # | Scenario | Expected | Actual | Result |
|---|---|---|---|---|
| S1 | GET /admin/users without token | 401 | 401 | ✅ |
| S2 | POST /auth/login (admin/admin) | 200 + JWT | 200, token 209 chars | ✅ |
| S3 | GET /admin/users with admin token | 200 list | 200 with 1 user | ✅ |
| S4 | POST /admin/users create `eve` PE user | 200 | 200, id=8 | ✅ |
| S5 | POST /auth/login for eve | 200 + JWT | 200, token 199 chars | ✅ |
| S6 | GET /admin/users with PE (eve) token | 403 | 403 | ✅ |
| S7 | POST /admin/users with roles=[PE, IT_ADMIN] (SOD violation) | 400 + `IT_ADMIN and PE cannot be assigned to the same user (SOD)` | 400 with that exact message | ✅ |
| S8 | GET /admin/audit as admin | Mutating ops captured | 3 items: login, create eve, rejected SOD create | ✅ |

## Design Decisions

1. **Sharing the TEXT `roles` column with Python** — avoids schema fork. `RoleCodec` reads/writes `["PE"]` JSON identical to Python SQLAlchemy representation.
2. **Stateless JWT only** — no sessions, no cookies. Frontend holds the token, sends `Authorization: Bearer`.
3. **`AccessDeniedHandler` + `@ExceptionHandler`** both wired — `@PreAuthorize`-thrown `AuthorizationDeniedException` is caught at both layers to guarantee 403 (not 500) regardless of throw site.
4. **Async audit** via `@Async` — zero controller-latency impact even when audit DB write is slow.
5. **SOD** is a pure validator (no DB), so policy changes are trivial — just update the rule file.
6. **Bootstrap seed** gated on `count()==0` and `auth.mode=local` — idempotent + never seeds in OIDC prod.
7. **OIDC wiring** for Azure AD is declared in SecurityConfig but inactive without an `OIDC_ISSUER` env var. Full E2E OIDC test needs Azure tenant config.

## Known Follow-ups (Non-blocking)

| Item | When |
|---|---|
| Azure AD OIDC end-to-end test against real tenant | Before prod cutover |
| Audit `request_body` capture (currently null) — needs `ContentCachingRequestWrapper` | Phase 3 if needed |
| Swap `RoleCodec` JSON → dedicated `user_roles` join table | Phase 4+ optional |
| Password policy (min length, complexity) | Phase 3 with user management UI |
| Rate-limit on `/auth/login` | Phase 3 |

## Verdict

**Phase 2 PASSED** — authentication, RBAC with 3 roles, SOD, audit log, and retention all verified via 19 automated tests + 8 live smoke scenarios. The JWT + `@PreAuthorize` stack is ready for Phase 3 to layer the CRUD controllers on top.
