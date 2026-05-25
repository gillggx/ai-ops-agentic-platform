# Multi-stage Dockerfile for aiops-app (Next.js standalone).
# Stage 1: build with full node_modules. Stage 2: only ship the standalone
# output + static + public. Final image ~200MB.
#
# Build context MUST be the repo root so the COPY of aiops-contract works:
#   docker build -f aiops-app/Dockerfile -t aiops-app .

FROM node:20.18-alpine AS deps
WORKDIR /build

# aiops-contract is referenced as `file:../aiops-contract/typescript` in
# aiops-app/package.json. Copy it FIRST so npm ci can resolve it.
COPY aiops-contract/typescript /build/aiops-contract/typescript
COPY aiops-app/package.json aiops-app/package-lock.json* /build/aiops-app/
WORKDIR /build/aiops-app
RUN npm ci --silent

FROM node:20.18-alpine AS builder
WORKDIR /build/aiops-app
COPY --from=deps /build/aiops-contract /build/aiops-contract
COPY --from=deps /build/aiops-app/node_modules ./node_modules
COPY aiops-app .

# build:prod runs scripts/check-prod-env.mjs first — required envs must be
# present at build time (Next.js inlines NEXT_PUBLIC_* and validates here).
ARG INTERNAL_API_TOKEN
ARG NEXTAUTH_SECRET
ARG FASTAPI_BASE_URL
ENV INTERNAL_API_TOKEN=$INTERNAL_API_TOKEN \
    NEXTAUTH_SECRET=$NEXTAUTH_SECRET \
    FASTAPI_BASE_URL=$FASTAPI_BASE_URL \
    NODE_ENV=production
RUN npm run build:prod

FROM node:20.18-alpine
WORKDIR /app

RUN addgroup -g 1001 -S nodejs && adduser -S -u 1001 -G nodejs nextjs

# Standalone output already includes a trimmed node_modules.
COPY --from=builder --chown=nextjs:nodejs /build/aiops-app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /build/aiops-app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /build/aiops-app/public ./public

USER nextjs
EXPOSE 8080
ENV PORT=8080 \
    HOSTNAME=0.0.0.0 \
    NODE_ENV=production

CMD ["node", "server.js"]
