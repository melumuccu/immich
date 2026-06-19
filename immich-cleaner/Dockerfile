# syntax=docker/dockerfile:1.7
#============================
# Base Layer
#============================
FROM node:24-slim AS base

ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
    PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH

RUN corepack enable
WORKDIR /workspace

#============================
# Dependencies Layer
#============================
FROM base AS deps

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY immich-cleaner/package.json ./immich-cleaner/package.json
RUN pnpm install --frozen-lockfile

#============================
# Build Layer
#============================
FROM deps AS build

COPY immich-cleaner ./immich-cleaner
RUN pnpm --dir immich-cleaner exec svelte-kit sync \
  && pnpm --dir immich-cleaner exec vite build

#============================
# Development Layer
#============================
FROM deps AS dev

ENV NODE_ENV=development \
    HOST=0.0.0.0 \
    PORT=2222 \
    IMMICH_CLEANER_DB_PATH=/app/data/immich-cleaner.sqlite3

COPY immich-cleaner ./immich-cleaner

WORKDIR /workspace/immich-cleaner

RUN mkdir -p /app/data \
  && pnpm exec svelte-kit sync

EXPOSE 2222

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:' + (process.env.PORT || 2222) + '/api/health').then((response) => process.exit(response.ok ? 0 : 1)).catch(() => process.exit(1))"

CMD ["pnpm", "exec", "vite", "dev", "--host", "0.0.0.0", "--port", "2222"]

#============================
# Runtime Layer
#============================
FROM node:24-slim AS runtime

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=2222 \
    IMMICH_CLEANER_DB_PATH=/app/data/immich-cleaner.sqlite3

WORKDIR /workspace/immich-cleaner

RUN groupadd --system --gid 1001 cleaner \
  && useradd --system --uid 1001 --gid cleaner --home-dir /workspace/immich-cleaner cleaner \
  && mkdir -p /app/data \
  && chown -R cleaner:cleaner /app /workspace

COPY --from=build --chown=cleaner:cleaner /workspace/node_modules /workspace/node_modules
COPY --from=build --chown=cleaner:cleaner /workspace/immich-cleaner/build ./build
COPY --from=build --chown=cleaner:cleaner /workspace/immich-cleaner/node_modules ./node_modules
COPY --from=build --chown=cleaner:cleaner /workspace/immich-cleaner/package.json ./package.json

USER cleaner

EXPOSE 2222

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:' + (process.env.PORT || 2222) + '/api/health').then((response) => process.exit(response.ok ? 0 : 1)).catch(() => process.exit(1))"

CMD ["node", "build"]
