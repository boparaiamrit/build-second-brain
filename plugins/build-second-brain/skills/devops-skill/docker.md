# Docker Reference — Dockerfiles, Compose, and Container Configuration

> Read this file when building Docker images, configuring docker-compose,
> or troubleshooting container issues.

---

## Table of Contents
1. [NestJS API Dockerfile](#nestjs-api-dockerfile)
2. [Next.js Frontend Dockerfile](#nextjs-frontend-dockerfile)
3. [Docker Compose — Local Development](#docker-compose--local-development)
4. [Docker Compose — Production](#docker-compose--production)
5. [.dockerignore](#dockerignore)
6. [Volume Mounts and Persistence](#volume-mounts-and-persistence)
7. [Network Configuration](#network-configuration)
8. [Health Check Configuration](#health-check-configuration)
9. [Resource Limits](#resource-limits)
10. [Troubleshooting](#troubleshooting)

---

## NestJS API Dockerfile

Multi-stage build: deps -> build -> production.

```dockerfile
# apps/api/Dockerfile

# ============================================================
# Stage 1: Install production dependencies only
# ============================================================
FROM node:22-alpine AS deps
WORKDIR /app

# Install system dependencies for native modules (bcrypt, sharp, etc.)
RUN apk add --no-cache python3 make g++

COPY package.json package-lock.json ./
COPY apps/api/package.json ./apps/api/
# If using monorepo with shared packages:
# COPY packages/shared/package.json ./packages/shared/

RUN npm ci --omit=dev --ignore-scripts \
  && npm rebuild bcrypt --build-from-source

# ============================================================
# Stage 2: Build the application
# ============================================================
FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
COPY apps/api/package.json ./apps/api/

RUN npm ci

# Copy source code
COPY apps/api/ ./apps/api/
# Copy shared packages if monorepo:
# COPY packages/shared/ ./packages/shared/

# Copy Prisma schema for generation
COPY apps/api/prisma/ ./apps/api/prisma/
RUN npx prisma generate --schema=./apps/api/prisma/schema.prisma

# Build
RUN npm run build --workspace=apps/api

# ============================================================
# Stage 3: Production image
# ============================================================
FROM node:22-alpine AS production
WORKDIR /app

# Security: run as non-root user
RUN addgroup --system --gid 1001 nodejs \
  && adduser --system --uid 1001 nestjs

# Copy production dependencies from deps stage
COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/apps/api/node_modules ./apps/api/node_modules

# Copy built application from build stage
COPY --from=build /app/apps/api/dist ./apps/api/dist

# Copy Prisma client (generated in build stage)
COPY --from=build /app/node_modules/.prisma ./node_modules/.prisma
COPY --from=build /app/apps/api/prisma ./apps/api/prisma

# Copy migration files (needed for prisma migrate deploy at runtime)
COPY apps/api/prisma/migrations ./apps/api/prisma/migrations
COPY apps/api/drizzle ./apps/api/drizzle

# Set environment
ENV NODE_ENV=production
ENV PORT=3001

# Expose port
EXPOSE 3001

# Switch to non-root user
USER nestjs

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:3001/health || exit 1

# Start the application
CMD ["node", "apps/api/dist/main.js"]
```

---

## Next.js Frontend Dockerfile

Multi-stage build with standalone output for minimal image size.

```dockerfile
# apps/web/Dockerfile

# ============================================================
# Stage 1: Install dependencies
# ============================================================
FROM node:22-alpine AS deps
WORKDIR /app

COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/

RUN npm ci

# ============================================================
# Stage 2: Build the application
# ============================================================
FROM node:22-alpine AS build
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/apps/web/node_modules ./apps/web/node_modules

COPY apps/web/ ./apps/web/
COPY package.json ./

# Build arguments for environment-specific builds
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_SENTRY_DSN
ARG NODE_ENV=production

ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_SENTRY_DSN=$NEXT_PUBLIC_SENTRY_DSN
ENV NODE_ENV=$NODE_ENV

# Enable standalone output in next.config.js:
#   output: 'standalone'
RUN npm run build --workspace=apps/web

# ============================================================
# Stage 3: Production image
# ============================================================
FROM node:22-alpine AS production
WORKDIR /app

# Security: run as non-root user
RUN addgroup --system --gid 1001 nodejs \
  && adduser --system --uid 1001 nextjs

# Copy standalone build output
COPY --from=build /app/apps/web/.next/standalone ./
COPY --from=build /app/apps/web/.next/static ./apps/web/.next/static
COPY --from=build /app/apps/web/public ./apps/web/public

# Set environment
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Expose port
EXPOSE 3000

# Switch to non-root user
USER nextjs

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:3000/api/health || exit 1

# Start the standalone server
CMD ["node", "apps/web/server.js"]
```

---

## Docker Compose -- Local Development

Full stack with hot reload, debug ports, and all supporting services.

```yaml
# docker-compose.yml — Local development
# Usage: docker compose up

services:
  # ============================================================
  # PostgreSQL + TimescaleDB
  # ============================================================
  postgres:
    image: timescale/timescaledb:latest-pg16
    container_name: sb-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${DB_USER:-postgres}
      POSTGRES_PASSWORD: ${DB_PASSWORD:-postgres}
      POSTGRES_DB: ${DB_NAME:-secondbrain}
    ports:
      - "${DB_PORT:-5432}:5432"
    volumes:
      - postgres-data:/var/lib/postgresql/data
      # Optional: init scripts for extensions
      - ./scripts/init-db.sql:/docker-entrypoint-initdb.d/01-init.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER:-postgres} -d ${DB_NAME:-secondbrain}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    networks:
      - data

  # ============================================================
  # Redis
  # ============================================================
  redis:
    image: redis:7-alpine
    container_name: sb-redis
    restart: unless-stopped
    command: >
      redis-server
        --appendonly yes
        --maxmemory 256mb
        --maxmemory-policy allkeys-lru
        --requirepass ${REDIS_PASSWORD:-}
    ports:
      - "${REDIS_PORT:-6379}:6379"
    volumes:
      - redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - data

  # ============================================================
  # NestJS API (Hot Reload)
  # ============================================================
  api:
    build:
      context: .
      dockerfile: apps/api/Dockerfile
      target: deps  # Stop at deps stage for dev
    container_name: sb-api
    restart: unless-stopped
    command: npm run start:dev --workspace=apps/api
    ports:
      - "${API_PORT:-3001}:3001"
      - "9229:9229"  # Node.js debugger port
    volumes:
      # Source code mount for hot reload
      - ./apps/api/src:/app/apps/api/src:delegated
      - ./apps/api/prisma:/app/apps/api/prisma:delegated
      - ./apps/api/drizzle:/app/apps/api/drizzle:delegated
      # Shared packages if monorepo
      # - ./packages/shared/src:/app/packages/shared/src:delegated
      # Prevent node_modules from being overwritten by mount
      - api-node-modules:/app/node_modules
    environment:
      NODE_ENV: development
      PORT: 3001
      DATABASE_URL: postgresql://${DB_USER:-postgres}:${DB_PASSWORD:-postgres}@postgres:5432/${DB_NAME:-secondbrain}
      REDIS_HOST: redis
      REDIS_PORT: 6379
      REDIS_PASSWORD: ${REDIS_PASSWORD:-}
      BULL_REDIS_HOST: redis
      BULL_REDIS_PORT: 6379
      BULL_REDIS_PASSWORD: ${REDIS_PASSWORD:-}
      JWT_SECRET: ${JWT_SECRET:-dev-secret-change-in-production-min32chars}
      LOG_LEVEL: debug
      FEATURE_FLAGS_PROVIDER: redis
    env_file:
      - .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:3001/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
    networks:
      - data
      - backend

  # ============================================================
  # BullMQ Workers (Hot Reload, separate from API)
  # ============================================================
  worker:
    build:
      context: .
      dockerfile: apps/api/Dockerfile
      target: deps
    container_name: sb-worker
    restart: unless-stopped
    command: npm run start:worker:dev --workspace=apps/api
    volumes:
      - ./apps/api/src:/app/apps/api/src:delegated
      - api-node-modules:/app/node_modules
    environment:
      NODE_ENV: development
      DATABASE_URL: postgresql://${DB_USER:-postgres}:${DB_PASSWORD:-postgres}@postgres:5432/${DB_NAME:-secondbrain}
      REDIS_HOST: redis
      REDIS_PORT: 6379
      REDIS_PASSWORD: ${REDIS_PASSWORD:-}
      BULL_REDIS_HOST: redis
      BULL_REDIS_PORT: 6379
      BULL_REDIS_PASSWORD: ${REDIS_PASSWORD:-}
      LOG_LEVEL: debug
    env_file:
      - .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - data
      - backend

  # ============================================================
  # Next.js Frontend (Hot Reload)
  # ============================================================
  web:
    build:
      context: .
      dockerfile: apps/web/Dockerfile
      target: deps
    container_name: sb-web
    restart: unless-stopped
    command: npm run dev --workspace=apps/web
    ports:
      - "${WEB_PORT:-3000}:3000"
    volumes:
      - ./apps/web/src:/app/apps/web/src:delegated
      - ./apps/web/public:/app/apps/web/public:delegated
      - web-node-modules:/app/node_modules
    environment:
      NODE_ENV: development
      NEXT_PUBLIC_API_URL: http://localhost:${API_PORT:-3001}
    env_file:
      - .env
    depends_on:
      api:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:3000"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    networks:
      - backend
      - frontend

  # ============================================================
  # Bull Board (Queue Monitoring UI)
  # ============================================================
  bull-board:
    build:
      context: .
      dockerfile: apps/api/Dockerfile
      target: deps
    container_name: sb-bull-board
    restart: unless-stopped
    command: npm run start:bull-board --workspace=apps/api
    ports:
      - "${BULL_BOARD_PORT:-3002}:3002"
    environment:
      PORT: 3002
      REDIS_HOST: redis
      REDIS_PORT: 6379
      REDIS_PASSWORD: ${REDIS_PASSWORD:-}
    depends_on:
      redis:
        condition: service_healthy
    networks:
      - data
      - backend

  # ============================================================
  # Jaeger (Distributed Tracing — local dev only)
  # ============================================================
  jaeger:
    image: jaegertracing/all-in-one:latest
    container_name: sb-jaeger
    restart: unless-stopped
    ports:
      - "16686:16686"  # Jaeger UI
      - "4318:4318"    # OTLP HTTP receiver
    environment:
      COLLECTOR_OTLP_ENABLED: "true"
    networks:
      - backend

volumes:
  postgres-data:
    driver: local
  redis-data:
    driver: local
  api-node-modules:
    driver: local
  web-node-modules:
    driver: local

networks:
  frontend:
    driver: bridge
  backend:
    driver: bridge
  data:
    driver: bridge
```

---

## Docker Compose -- Production

Production-ready configuration with resource limits, restart policies, and no hot reload.

```yaml
# docker-compose.prod.yml — Production / Staging
# Usage: TAG=prod-abc123 docker compose -f docker-compose.prod.yml up -d

services:
  # ============================================================
  # PostgreSQL + TimescaleDB
  # ============================================================
  postgres:
    image: timescale/timescaledb:latest-pg16
    container_name: sb-postgres
    restart: always
    environment:
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: ${DB_NAME}
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER} -d ${DB_NAME}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: '2.0'
        reservations:
          memory: 1G
          cpus: '1.0'
    networks:
      - data
    # IMPORTANT: No ports exposed — only reachable via internal network

  # ============================================================
  # Redis
  # ============================================================
  redis:
    image: redis:7-alpine
    container_name: sb-redis
    restart: always
    command: >
      redis-server
        --appendonly yes
        --maxmemory 512mb
        --maxmemory-policy allkeys-lru
        --requirepass ${REDIS_PASSWORD}
        --tcp-backlog 511
        --timeout 300
    volumes:
      - redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 768M
          cpus: '1.0'
        reservations:
          memory: 256M
          cpus: '0.25'
    networks:
      - data

  # ============================================================
  # NestJS API
  # ============================================================
  api:
    image: ${REGISTRY:-ghcr.io/your-org/your-repo}/api:${TAG:-latest}
    container_name: sb-api
    restart: always
    ports:
      - "${API_PORT:-3001}:3001"
    environment:
      NODE_ENV: production
      PORT: 3001
      DATABASE_URL: postgresql://${DB_USER}:${DB_PASSWORD}@postgres:5432/${DB_NAME}?sslmode=prefer
      REDIS_HOST: redis
      REDIS_PORT: 6379
      REDIS_PASSWORD: ${REDIS_PASSWORD}
      BULL_REDIS_HOST: redis
      BULL_REDIS_PORT: 6379
      BULL_REDIS_PASSWORD: ${REDIS_PASSWORD}
      JWT_SECRET: ${JWT_SECRET}
      SENTRY_DSN: ${SENTRY_DSN}
      SENTRY_ENVIRONMENT: ${SENTRY_ENVIRONMENT:-production}
      LOG_LEVEL: ${LOG_LEVEL:-warn}
      FEATURE_FLAGS_PROVIDER: ${FEATURE_FLAGS_PROVIDER:-redis}
      UNLEASH_URL: ${UNLEASH_URL:-}
      UNLEASH_API_KEY: ${UNLEASH_API_KEY:-}
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:3001/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    deploy:
      replicas: ${API_REPLICAS:-2}
      resources:
        limits:
          memory: 1G
          cpus: '1.0'
        reservations:
          memory: 512M
          cpus: '0.5'
      restart_policy:
        condition: on-failure
        delay: 5s
        max_attempts: 3
        window: 120s
    networks:
      - data
      - backend

  # ============================================================
  # BullMQ Workers
  # ============================================================
  worker:
    image: ${REGISTRY:-ghcr.io/your-org/your-repo}/api:${TAG:-latest}
    command: ["node", "apps/api/dist/worker.js"]
    restart: always
    environment:
      NODE_ENV: production
      DATABASE_URL: postgresql://${DB_USER}:${DB_PASSWORD}@postgres:5432/${DB_NAME}?sslmode=prefer
      REDIS_HOST: redis
      REDIS_PORT: 6379
      REDIS_PASSWORD: ${REDIS_PASSWORD}
      BULL_REDIS_HOST: redis
      BULL_REDIS_PORT: 6379
      BULL_REDIS_PASSWORD: ${REDIS_PASSWORD}
      SENTRY_DSN: ${SENTRY_DSN}
      SENTRY_ENVIRONMENT: ${SENTRY_ENVIRONMENT:-production}
      LOG_LEVEL: ${LOG_LEVEL:-warn}
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    deploy:
      replicas: ${WORKER_REPLICAS:-2}
      resources:
        limits:
          memory: 512M
          cpus: '0.5'
        reservations:
          memory: 256M
          cpus: '0.25'
      restart_policy:
        condition: on-failure
        delay: 5s
        max_attempts: 5
        window: 120s
    networks:
      - data
      - backend

  # ============================================================
  # Next.js Frontend
  # ============================================================
  web:
    image: ${REGISTRY:-ghcr.io/your-org/your-repo}/web:${TAG:-latest}
    container_name: sb-web
    restart: always
    ports:
      - "${WEB_PORT:-3000}:3000"
    environment:
      NODE_ENV: production
      NEXT_PUBLIC_API_URL: ${NEXT_PUBLIC_API_URL}
    depends_on:
      api:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:3000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    deploy:
      replicas: ${WEB_REPLICAS:-2}
      resources:
        limits:
          memory: 512M
          cpus: '0.5'
        reservations:
          memory: 256M
          cpus: '0.25'
      restart_policy:
        condition: on-failure
        delay: 5s
        max_attempts: 3
        window: 120s
    networks:
      - backend
      - frontend

volumes:
  postgres-data:
    driver: local
  redis-data:
    driver: local

networks:
  frontend:
    driver: bridge
  backend:
    driver: bridge
  data:
    driver: bridge
```

---

## .dockerignore

Place at the repository root. Prevents large/sensitive files from entering build context.

```dockerignore
# .dockerignore

# Dependencies (reinstalled in Docker)
node_modules
**/node_modules

# Build outputs (rebuilt in Docker)
dist
**/dist
.next
**/.next

# Git
.git
.gitignore

# Environment files (secrets must not be baked into images)
.env
.env.*
!.env.example

# IDE
.vscode
.idea
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Testing
coverage
**/__tests__
**/*.test.ts
**/*.spec.ts
playwright-report
test-results

# Documentation (not needed in runtime image)
*.md
docs/
LICENSE

# Docker (prevent recursive context)
docker-compose*.yml
Dockerfile*

# CI/CD
.github
.gitlab-ci.yml

# Skills and planning
.claude
.planning
skills
```

---

## Volume Mounts and Persistence

### Development Volumes

```yaml
volumes:
  # Database persistence — survives container restarts
  postgres-data:
    driver: local

  # Redis persistence — AOF for durability
  redis-data:
    driver: local

  # node_modules isolation — prevents host OS mismatch (especially Windows/Mac vs Linux)
  api-node-modules:
    driver: local
  web-node-modules:
    driver: local
```

### Source Code Mounts

```yaml
# Use :delegated for better performance on macOS
# Source mounts enable hot reload without rebuilding the container
volumes:
  - ./apps/api/src:/app/apps/api/src:delegated    # API source
  - ./apps/web/src:/app/apps/web/src:delegated     # Frontend source
```

### Rules

| Rule | Why |
|------|-----|
| Never mount `node_modules` from host | Host OS native modules (bcrypt, etc.) are incompatible with Linux container |
| Use named volumes for `node_modules` | Named volumes persist across container restarts, avoid rebuild |
| Use `:delegated` on macOS | Reduces filesystem sync overhead for better performance |
| Never mount `.env` in production compose | Secrets injected via environment variables, not files |
| Persist database volumes | Losing `postgres-data` means losing all development data |

---

## Network Configuration

### Development Networks

```
frontend network:     web (Next.js)
backend network:      web, api, worker, bull-board
data network:         api, worker, postgres, redis
```

### Network Isolation Rules

| Service | Can reach | Cannot reach |
|---------|-----------|-------------|
| web (Next.js) | api | postgres, redis directly |
| api (NestJS) | postgres, redis, web (for callbacks) | External internet (except explicit allowlist) |
| worker | postgres, redis | web, external internet |
| postgres | Nothing (accepts connections only) | Everything |
| redis | Nothing (accepts connections only) | Everything |

### DNS Resolution

Inside Docker Compose, services reference each other by service name:

```
# From api container:
postgres → resolves to postgres container IP
redis → resolves to redis container IP

# WRONG — do not use localhost or 127.0.0.1 inside containers
DATABASE_URL=postgresql://user:pass@localhost:5432/db     # BREAKS
DATABASE_URL=postgresql://user:pass@postgres:5432/db      # WORKS
```

---

## Health Check Configuration

### Per-Service Health Checks

```yaml
# PostgreSQL
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U postgres -d secondbrain"]
  interval: 10s      # Check every 10 seconds
  timeout: 5s        # Fail if check takes >5 seconds
  retries: 5         # Mark unhealthy after 5 failures
  start_period: 30s  # Grace period for startup

# Redis
healthcheck:
  test: ["CMD", "redis-cli", "ping"]
  interval: 10s
  timeout: 5s
  retries: 5

# NestJS API
healthcheck:
  test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:3001/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 60s  # NestJS needs time to connect to DB + Redis

# Next.js
healthcheck:
  test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:3000/api/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 30s
```

### Dependency Health Ordering

```yaml
# Services wait for dependencies to be healthy, not just started
api:
  depends_on:
    postgres:
      condition: service_healthy   # Wait for pg_isready
    redis:
      condition: service_healthy   # Wait for redis-cli ping

worker:
  depends_on:
    postgres:
      condition: service_healthy
    redis:
      condition: service_healthy

web:
  depends_on:
    api:
      condition: service_healthy   # Wait for /health endpoint
```

---

## Resource Limits

### Production Resource Allocation

| Service | Memory Limit | CPU Limit | Memory Reserve | CPU Reserve |
|---------|-------------|-----------|---------------|------------|
| PostgreSQL | 2G | 2.0 | 1G | 1.0 |
| Redis | 768M | 1.0 | 256M | 0.25 |
| API (per replica) | 1G | 1.0 | 512M | 0.5 |
| Worker (per replica) | 512M | 0.5 | 256M | 0.25 |
| Web (per replica) | 512M | 0.5 | 256M | 0.25 |

### Scaling Rules

```bash
# Scale workers based on queue depth
docker compose -f docker-compose.prod.yml up -d --scale worker=4

# Scale API based on request volume
docker compose -f docker-compose.prod.yml up -d --scale api=3

# Scale frontend based on traffic
docker compose -f docker-compose.prod.yml up -d --scale web=2
```

---

## Troubleshooting

### Common Issues

**Container exits immediately:**
```bash
# Check logs
docker compose logs api --tail 100

# Common cause: missing environment variable
# Fix: ensure .env file exists and all required vars are set
```

**Port already in use:**
```bash
# Find what is using the port
lsof -i :3001  # macOS/Linux
netstat -ano | findstr :3001  # Windows

# Fix: change port in .env or stop conflicting process
```

**Database connection refused:**
```bash
# Check if postgres is healthy
docker compose ps postgres

# Check postgres logs
docker compose logs postgres --tail 50

# Common cause: postgres not ready yet
# Fix: depends_on with condition: service_healthy
```

**node_modules mismatch (native modules):**
```bash
# Symptom: "Error: ... was compiled against a different Node.js version"
# Cause: host node_modules mounted into container

# Fix: use named volume for node_modules
docker compose down
docker volume rm sb-api-node-modules
docker compose up --build
```

**Slow file watching on macOS/Windows:**
```bash
# Symptom: hot reload takes 5-10 seconds instead of <1 second
# Cause: filesystem notification overhead across Docker mount

# Fix 1: use :delegated mount option
# Fix 2: use polling-based file watching
# In NestJS: nest start --watch --watchAssets
# In Next.js: WATCHPACK_POLLING=true in environment
```

**Disk space full from Docker:**
```bash
# Clean up unused images, containers, volumes
docker system prune -a --volumes

# Check disk usage
docker system df
```
