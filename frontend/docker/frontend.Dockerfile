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
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ARG NEXT_PUBLIC_BASE_PATH=
ENV NEXT_PUBLIC_BASE_PATH=${NEXT_PUBLIC_BASE_PATH}
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
# The frontend is built as a self-contained project, so Next emits server.js at
# the root of its standalone output.
COPY --from=builder --chown=cri:cri /app/.next/standalone ./
COPY --from=builder --chown=cri:cri /app/.next/static ./.next/static

USER cri

EXPOSE 3000
ENV PORT=3000

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD node -e "const s=require('net').connect(3000,'127.0.0.1'); s.on('connect',()=>process.exit(0)); s.on('error',()=>process.exit(1)); setTimeout(()=>process.exit(1),3000)"

CMD ["node", "server.js"]
