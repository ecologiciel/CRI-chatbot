# =============================================================================
# CRI Chatbot Platform — Frontend Dockerfile (multi-stage)
# =============================================================================

# Stage 1: Dependencies
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

# Stage 2: Builder
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# Stage 3: Runner — minimal production image
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Security: non-root user (matching backend convention)
RUN addgroup -S cri && adduser -S cri -G cri

# Copy standalone output
COPY --from=builder /app/public ./public
COPY --from=builder --chown=cri:cri /app/.next/standalone ./
COPY --from=builder --chown=cri:cri /app/.next/static ./.next/static

USER cri

EXPOSE 3000
ENV PORT=3000

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost:3000/ || exit 1

CMD ["node", "server.js"]
