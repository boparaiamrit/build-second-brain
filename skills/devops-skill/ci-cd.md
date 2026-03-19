# CI/CD Reference — GitHub Actions, Branch Strategy, Deployment Pipelines

> Read this file when setting up CI/CD pipelines, configuring GitHub Actions,
> or automating deployment workflows.

---

## Table of Contents
1. [Branch Strategy](#branch-strategy)
2. [PR Check Workflow](#pr-check-workflow)
3. [Deploy Staging Workflow](#deploy-staging-workflow)
4. [Deploy Production Workflow](#deploy-production-workflow)
5. [Database Migration Workflow](#database-migration-workflow)
6. [E2E Test Workflow](#e2e-test-workflow)
7. [Docker Image Build](#docker-image-build)
8. [Environment Variables in CI](#environment-variables-in-ci)
9. [Rollback Procedure](#rollback-procedure)
10. [Notification Setup](#notification-setup)

---

## Branch Strategy

```
main          ← Production. Protected. Requires PR + approval + passing checks.
develop       ← Staging. Auto-deploys on merge. Integration testing happens here.
feature/*     ← Feature branches. PRs target develop.
hotfix/*      ← Emergency fixes. PRs target main directly.
release/*     ← Release candidates. Cut from develop, merge to main + develop.
```

### Branch Rules

| Branch | Push | Merge | Deploy | Tests |
|--------|------|-------|--------|-------|
| `main` | Blocked | PR only, 1 approval required | Auto → production | All must pass |
| `develop` | Blocked | PR only, CI must pass | Auto → staging | All must pass |
| `feature/*` | Allowed | PR to develop | None | PR checks |
| `hotfix/*` | Allowed | PR to main (fast-track) | None | PR checks |
| `release/*` | Allowed | PR to main + back-merge to develop | None | PR checks + E2E |

### Commit Convention

```
type(scope): description

feat(campaigns): add timezone-aware scheduling
fix(recipients): prevent duplicate imports for same domain
chore(deps): upgrade NestJS to v11
refactor(auth): extract JWT validation to shared guard
docs(api): update OpenAPI spec for bulk endpoints
test(import): add E2E test for CSV import with 10k rows
perf(queries): add composite index for recipient search
ci(actions): parallelize test jobs
```

---

## PR Check Workflow

Runs on every pull request. Must pass before merge.

```yaml
# .github/workflows/pr-check.yml
name: PR Check

on:
  pull_request:
    branches: [main, develop]

concurrency:
  group: pr-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  lint-and-typecheck:
    name: Lint + Type Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: 'npm'

      - run: npm ci

      - name: Lint
        run: npm run lint

      - name: Type Check
        run: npx tsc --noEmit

  test-unit:
    name: Unit Tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: 'npm'

      - run: npm ci

      - name: Run Unit Tests
        run: npm run test -- --coverage --ci
        env:
          NODE_ENV: test

      - name: Upload Coverage
        uses: actions/upload-artifact@v4
        with:
          name: coverage
          path: coverage/

  test-integration:
    name: Integration Tests
    runs-on: ubuntu-latest
    services:
      postgres:
        image: timescale/timescaledb:latest-pg16
        env:
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
          POSTGRES_DB: test_db
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U test"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: 'npm'

      - run: npm ci

      - name: Run Prisma Migrations
        run: npx prisma migrate deploy
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/test_db

      - name: Run Drizzle Migrations
        run: npx drizzle-kit migrate
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/test_db

      - name: Run Integration Tests
        run: npm run test:integration -- --ci
        env:
          NODE_ENV: test
          DATABASE_URL: postgresql://test:test@localhost:5432/test_db
          REDIS_HOST: localhost
          REDIS_PORT: 6379

  build:
    name: Build Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: 'npm'

      - run: npm ci

      - name: Build API
        run: npm run build
        working-directory: apps/api

      - name: Build Frontend
        run: npm run build
        working-directory: apps/web

  docker-build:
    name: Docker Build Test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build API Image (test only, no push)
        uses: docker/build-push-action@v5
        with:
          context: .
          file: ./apps/api/Dockerfile
          push: false
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

---

## Deploy Staging Workflow

Automatically deploys to staging when code is merged to `develop`.

```yaml
# .github/workflows/deploy-staging.yml
name: Deploy Staging

on:
  push:
    branches: [develop]

concurrency:
  group: deploy-staging
  cancel-in-progress: false  # Never cancel a deploy in progress

env:
  REGISTRY: ghcr.io/${{ github.repository }}
  TAG: staging-${{ github.sha }}

jobs:
  build-and-push:
    name: Build & Push Docker Images
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4

      - name: Log in to Container Registry
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build and Push API Image
        uses: docker/build-push-action@v5
        with:
          context: .
          file: ./apps/api/Dockerfile
          push: true
          tags: |
            ${{ env.REGISTRY }}/api:${{ env.TAG }}
            ${{ env.REGISTRY }}/api:staging-latest
          cache-from: type=gha
          cache-to: type=gha,mode=max
          build-args: |
            NODE_ENV=staging

      - name: Build and Push Web Image
        uses: docker/build-push-action@v5
        with:
          context: .
          file: ./apps/web/Dockerfile
          push: true
          tags: |
            ${{ env.REGISTRY }}/web:${{ env.TAG }}
            ${{ env.REGISTRY }}/web:staging-latest
          cache-from: type=gha
          cache-to: type=gha,mode=max
          build-args: |
            NODE_ENV=staging

  migrate:
    name: Run Database Migrations
    needs: build-and-push
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: 'npm'

      - run: npm ci

      - name: Run Prisma Migrations
        run: npx prisma migrate deploy
        env:
          DATABASE_URL: ${{ secrets.STAGING_DATABASE_URL }}

      - name: Run Drizzle Migrations
        run: npx drizzle-kit migrate
        env:
          DATABASE_URL: ${{ secrets.STAGING_DATABASE_URL }}

      - name: Run TimescaleDB Setup
        run: node scripts/timescaledb-setup.js
        env:
          DATABASE_URL: ${{ secrets.STAGING_DATABASE_URL }}

  deploy:
    name: Deploy to Staging
    needs: [build-and-push, migrate]
    runs-on: ubuntu-latest
    environment: staging
    steps:
      - uses: actions/checkout@v4

      # ---- Cloud-agnostic deployment step ----
      # Replace this section with your cloud provider's deployment action:
      #
      # AWS ECS:
      #   - uses: aws-actions/amazon-ecs-deploy-task-definition@v1
      #     with:
      #       task-definition: task-def.json
      #       service: staging-api
      #       cluster: staging-cluster
      #
      # GCP Cloud Run:
      #   - uses: google-github-actions/deploy-cloudrun@v1
      #     with:
      #       service: staging-api
      #       image: ${{ env.REGISTRY }}/api:${{ env.TAG }}
      #
      # Railway:
      #   - run: railway up --service api --environment staging
      #
      # Generic (SSH + docker compose):
      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.STAGING_HOST }}
          username: ${{ secrets.STAGING_USER }}
          key: ${{ secrets.STAGING_SSH_KEY }}
          script: |
            cd /opt/app
            export TAG=${{ env.TAG }}
            docker compose -f docker-compose.prod.yml pull
            docker compose -f docker-compose.prod.yml up -d --remove-orphans
            docker system prune -f

  smoke-test:
    name: Smoke Test
    needs: deploy
    runs-on: ubuntu-latest
    steps:
      - name: Wait for deployment to stabilize
        run: sleep 30

      - name: Health Check
        run: |
          for i in {1..10}; do
            STATUS=$(curl -s -o /dev/null -w "%{http_code}" ${{ secrets.STAGING_URL }}/health)
            if [ "$STATUS" = "200" ]; then
              echo "Health check passed"
              exit 0
            fi
            echo "Attempt $i: got $STATUS, retrying in 10s..."
            sleep 10
          done
          echo "Health check failed after 10 attempts"
          exit 1

      - name: API Smoke Test
        run: |
          RESPONSE=$(curl -s ${{ secrets.STAGING_URL }}/health)
          echo "$RESPONSE" | jq .
          # Verify all services are healthy
          echo "$RESPONSE" | jq -e '.status == "ok"'

  notify:
    name: Notify
    needs: [deploy, smoke-test]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - name: Notify Success
        if: needs.deploy.result == 'success' && needs.smoke-test.result == 'success'
        run: |
          curl -X POST "${{ secrets.SLACK_WEBHOOK_URL }}" \
            -H 'Content-type: application/json' \
            -d '{
              "text": "Staging deployed successfully :white_check_mark:",
              "blocks": [
                {
                  "type": "section",
                  "text": {
                    "type": "mrkdwn",
                    "text": "*Staging Deploy Succeeded*\nCommit: `${{ github.sha }}`\nActor: ${{ github.actor }}\nURL: ${{ secrets.STAGING_URL }}"
                  }
                }
              ]
            }'

      - name: Notify Failure
        if: needs.deploy.result == 'failure' || needs.smoke-test.result == 'failure'
        run: |
          curl -X POST "${{ secrets.SLACK_WEBHOOK_URL }}" \
            -H 'Content-type: application/json' \
            -d '{
              "text": "Staging deploy FAILED :x:",
              "blocks": [
                {
                  "type": "section",
                  "text": {
                    "type": "mrkdwn",
                    "text": "*Staging Deploy FAILED*\nCommit: `${{ github.sha }}`\nActor: ${{ github.actor }}\nWorkflow: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"
                  }
                }
              ]
            }'
```

---

## Deploy Production Workflow

Deploys to production when code is merged to `main`. Requires manual approval.

```yaml
# .github/workflows/deploy-production.yml
name: Deploy Production

on:
  push:
    branches: [main]

concurrency:
  group: deploy-production
  cancel-in-progress: false

env:
  REGISTRY: ghcr.io/${{ github.repository }}
  TAG: prod-${{ github.sha }}

jobs:
  build-and-push:
    name: Build & Push Docker Images
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4

      - name: Log in to Container Registry
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build and Push API Image
        uses: docker/build-push-action@v5
        with:
          context: .
          file: ./apps/api/Dockerfile
          push: true
          tags: |
            ${{ env.REGISTRY }}/api:${{ env.TAG }}
            ${{ env.REGISTRY }}/api:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max
          build-args: |
            NODE_ENV=production

      - name: Build and Push Web Image
        uses: docker/build-push-action@v5
        with:
          context: .
          file: ./apps/web/Dockerfile
          push: true
          tags: |
            ${{ env.REGISTRY }}/web:${{ env.TAG }}
            ${{ env.REGISTRY }}/web:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max
          build-args: |
            NODE_ENV=production

  migrate:
    name: Run Database Migrations
    needs: build-and-push
    runs-on: ubuntu-latest
    environment: production  # Requires approval
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: 'npm'

      - run: npm ci

      - name: Run Prisma Migrations
        run: npx prisma migrate deploy
        env:
          DATABASE_URL: ${{ secrets.PRODUCTION_DATABASE_URL }}

      - name: Run Drizzle Migrations
        run: npx drizzle-kit migrate
        env:
          DATABASE_URL: ${{ secrets.PRODUCTION_DATABASE_URL }}

      - name: Run TimescaleDB Setup
        run: node scripts/timescaledb-setup.js
        env:
          DATABASE_URL: ${{ secrets.PRODUCTION_DATABASE_URL }}

  deploy:
    name: Deploy to Production
    needs: [build-and-push, migrate]
    runs-on: ubuntu-latest
    environment: production  # Requires approval
    steps:
      - uses: actions/checkout@v4

      # ---- Cloud-agnostic deployment step ----
      # Replace with your cloud provider's deployment action (see staging example)
      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.PRODUCTION_HOST }}
          username: ${{ secrets.PRODUCTION_USER }}
          key: ${{ secrets.PRODUCTION_SSH_KEY }}
          script: |
            cd /opt/app
            export TAG=${{ env.TAG }}
            docker compose -f docker-compose.prod.yml pull
            docker compose -f docker-compose.prod.yml up -d --remove-orphans
            docker system prune -f

  smoke-test:
    name: Production Smoke Test
    needs: deploy
    runs-on: ubuntu-latest
    steps:
      - name: Wait for deployment to stabilize
        run: sleep 30

      - name: Health Check
        run: |
          for i in {1..15}; do
            STATUS=$(curl -s -o /dev/null -w "%{http_code}" ${{ secrets.PRODUCTION_URL }}/health)
            if [ "$STATUS" = "200" ]; then
              echo "Health check passed"
              exit 0
            fi
            echo "Attempt $i: got $STATUS, retrying in 10s..."
            sleep 10
          done
          echo "Health check failed after 15 attempts"
          exit 1

      - name: API Smoke Test
        run: |
          RESPONSE=$(curl -s ${{ secrets.PRODUCTION_URL }}/health)
          echo "$RESPONSE" | jq .
          echo "$RESPONSE" | jq -e '.status == "ok"'
          echo "$RESPONSE" | jq -e '.info.database.status == "up"'
          echo "$RESPONSE" | jq -e '.info.redis.status == "up"'

  notify:
    name: Notify
    needs: [deploy, smoke-test]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - name: Notify Success
        if: needs.deploy.result == 'success' && needs.smoke-test.result == 'success'
        run: |
          curl -X POST "${{ secrets.SLACK_WEBHOOK_URL }}" \
            -H 'Content-type: application/json' \
            -d '{
              "text": "Production deployed successfully :rocket:",
              "blocks": [
                {
                  "type": "section",
                  "text": {
                    "type": "mrkdwn",
                    "text": "*Production Deploy Succeeded*\nCommit: `${{ github.sha }}`\nActor: ${{ github.actor }}\nURL: ${{ secrets.PRODUCTION_URL }}"
                  }
                }
              ]
            }'

      - name: Notify Failure
        if: needs.deploy.result == 'failure' || needs.smoke-test.result == 'failure'
        run: |
          curl -X POST "${{ secrets.SLACK_WEBHOOK_URL }}" \
            -H 'Content-type: application/json' \
            -d '{
              "text": "PRODUCTION DEPLOY FAILED :rotating_light:",
              "blocks": [
                {
                  "type": "section",
                  "text": {
                    "type": "mrkdwn",
                    "text": "*PRODUCTION Deploy FAILED*\nCommit: `${{ github.sha }}`\nActor: ${{ github.actor }}\n*Action Required:* ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"
                  }
                }
              ]
            }'
```

---

## Database Migration Workflow

Standalone migration workflow that can be triggered manually for emergency migrations.

```yaml
# .github/workflows/migrate.yml
name: Database Migration

on:
  workflow_dispatch:
    inputs:
      environment:
        description: 'Target environment'
        required: true
        type: choice
        options:
          - staging
          - production
      migration_type:
        description: 'Migration type'
        required: true
        type: choice
        options:
          - all
          - prisma-only
          - drizzle-only
          - timescaledb-only
      dry_run:
        description: 'Dry run (show what would change without applying)'
        required: false
        type: boolean
        default: true

jobs:
  migrate:
    name: Run Migration (${{ inputs.environment }})
    runs-on: ubuntu-latest
    environment: ${{ inputs.environment }}
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: 'npm'

      - run: npm ci

      - name: Set Database URL
        run: |
          if [ "${{ inputs.environment }}" = "production" ]; then
            echo "DATABASE_URL=${{ secrets.PRODUCTION_DATABASE_URL }}" >> $GITHUB_ENV
          else
            echo "DATABASE_URL=${{ secrets.STAGING_DATABASE_URL }}" >> $GITHUB_ENV
          fi

      - name: Prisma Migration
        if: inputs.migration_type == 'all' || inputs.migration_type == 'prisma-only'
        run: |
          if [ "${{ inputs.dry_run }}" = "true" ]; then
            echo "=== DRY RUN: Prisma migration status ==="
            npx prisma migrate status
          else
            echo "=== APPLYING: Prisma migrations ==="
            npx prisma migrate deploy
          fi

      - name: Drizzle Migration
        if: inputs.migration_type == 'all' || inputs.migration_type == 'drizzle-only'
        run: |
          if [ "${{ inputs.dry_run }}" = "true" ]; then
            echo "=== DRY RUN: Drizzle migration check ==="
            npx drizzle-kit check
          else
            echo "=== APPLYING: Drizzle migrations ==="
            npx drizzle-kit migrate
          fi

      - name: TimescaleDB Setup
        if: inputs.migration_type == 'all' || inputs.migration_type == 'timescaledb-only'
        run: |
          if [ "${{ inputs.dry_run }}" = "true" ]; then
            echo "=== DRY RUN: TimescaleDB setup (idempotent, safe to run) ==="
          fi
          # TimescaleDB scripts use IF NOT EXISTS — safe to run repeatedly
          node scripts/timescaledb-setup.js
```

---

## E2E Test Workflow

Runs Playwright E2E tests with full database seeding.

```yaml
# .github/workflows/e2e.yml
name: E2E Tests

on:
  pull_request:
    branches: [main]
  workflow_dispatch:

jobs:
  e2e:
    name: Playwright E2E Tests
    runs-on: ubuntu-latest
    timeout-minutes: 30

    services:
      postgres:
        image: timescale/timescaledb:latest-pg16
        env:
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
          POSTGRES_DB: e2e_db
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U test"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: 'npm'

      - run: npm ci

      - name: Install Playwright Browsers
        run: npx playwright install --with-deps chromium

      - name: Run Migrations
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/e2e_db
        run: |
          npx prisma migrate deploy
          npx drizzle-kit migrate
          node scripts/timescaledb-setup.js

      - name: Seed Database
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/e2e_db
        run: npm run db:seed:e2e

      - name: Start API Server
        env:
          NODE_ENV: test
          DATABASE_URL: postgresql://test:test@localhost:5432/e2e_db
          REDIS_HOST: localhost
          REDIS_PORT: 6379
          PORT: 3001
          JWT_SECRET: e2e-test-secret-minimum-32-chars!!
        run: |
          npm run start:prod &
          # Wait for API to be ready
          for i in {1..30}; do
            if curl -s http://localhost:3001/health > /dev/null 2>&1; then
              echo "API is ready"
              break
            fi
            sleep 2
          done

      - name: Start Frontend
        env:
          NEXT_PUBLIC_API_URL: http://localhost:3001
        run: |
          npm run start --prefix apps/web &
          # Wait for frontend to be ready
          for i in {1..30}; do
            if curl -s http://localhost:3000 > /dev/null 2>&1; then
              echo "Frontend is ready"
              break
            fi
            sleep 2
          done

      - name: Run Playwright Tests
        env:
          BASE_URL: http://localhost:3000
          API_URL: http://localhost:3001
        run: npx playwright test

      - name: Upload Test Results
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: playwright-report
          path: playwright-report/
          retention-days: 7

      - name: Upload Test Screenshots
        uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: playwright-screenshots
          path: test-results/
          retention-days: 7
```

---

## Docker Image Build

### Build Arguments and Caching

```yaml
# Reusable composite action for Docker builds
# .github/actions/docker-build/action.yml
name: Docker Build & Push
description: Build and optionally push a Docker image with caching

inputs:
  image_name:
    description: 'Image name (e.g., api, web)'
    required: true
  dockerfile:
    description: 'Path to Dockerfile'
    required: true
  context:
    description: 'Build context path'
    default: '.'
  push:
    description: 'Push to registry'
    default: 'false'
  tags:
    description: 'Image tags (newline-separated)'
    required: true

runs:
  using: composite
  steps:
    - name: Set up Docker Buildx
      uses: docker/setup-buildx-action@v3

    - name: Build and Push
      uses: docker/build-push-action@v5
      with:
        context: ${{ inputs.context }}
        file: ${{ inputs.dockerfile }}
        push: ${{ inputs.push }}
        tags: ${{ inputs.tags }}
        cache-from: type=gha,scope=${{ inputs.image_name }}
        cache-to: type=gha,mode=max,scope=${{ inputs.image_name }}
        labels: |
          org.opencontainers.image.source=${{ github.server_url }}/${{ github.repository }}
          org.opencontainers.image.revision=${{ github.sha }}
          org.opencontainers.image.created=${{ github.event.head_commit.timestamp }}
```

---

## Environment Variables in CI

### GitHub Actions Secrets Setup

```
Repository Settings → Secrets and variables → Actions

Required secrets per environment:

=== Staging ===
STAGING_DATABASE_URL          postgresql://user:pass@host:5432/staging_db
STAGING_HOST                  staging.example.com
STAGING_USER                  deploy
STAGING_SSH_KEY               (private key for SSH deployment)
STAGING_URL                   https://staging.example.com

=== Production ===
PRODUCTION_DATABASE_URL       postgresql://user:pass@host:5432/prod_db
PRODUCTION_HOST               app.example.com
PRODUCTION_USER               deploy
PRODUCTION_SSH_KEY            (private key for SSH deployment)
PRODUCTION_URL                https://app.example.com

=== Shared ===
SLACK_WEBHOOK_URL             https://hooks.slack.com/services/...
SENTRY_AUTH_TOKEN             (for source map upload)
SENTRY_ORG                   your-org
SENTRY_PROJECT_API            your-api-project
SENTRY_PROJECT_WEB            your-web-project
```

### Environment Protection Rules

```
Repository Settings → Environments

staging:
  - No protection rules (auto-deploy on merge to develop)

production:
  - Required reviewers: 1 (team lead or senior engineer)
  - Wait timer: 0 (deploy immediately after approval)
  - Deployment branches: main only
```

---

## Rollback Procedure

### Automated Rollback (Recommended)

```yaml
# .github/workflows/rollback.yml
name: Rollback

on:
  workflow_dispatch:
    inputs:
      environment:
        description: 'Target environment'
        required: true
        type: choice
        options:
          - staging
          - production
      rollback_type:
        description: 'Rollback method'
        required: true
        type: choice
        options:
          - revert-commit     # Git revert + redeploy (safest)
          - previous-image    # Redeploy previous Docker image (fastest)
      image_tag:
        description: 'Image tag to rollback to (only for previous-image type)'
        required: false
        type: string

jobs:
  rollback:
    name: Rollback ${{ inputs.environment }}
    runs-on: ubuntu-latest
    environment: ${{ inputs.environment }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Revert Commit
        if: inputs.rollback_type == 'revert-commit'
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git revert HEAD --no-edit
          git push

      - name: Deploy Previous Image
        if: inputs.rollback_type == 'previous-image'
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ inputs.environment == 'production' && secrets.PRODUCTION_HOST || secrets.STAGING_HOST }}
          username: ${{ inputs.environment == 'production' && secrets.PRODUCTION_USER || secrets.STAGING_USER }}
          key: ${{ inputs.environment == 'production' && secrets.PRODUCTION_SSH_KEY || secrets.STAGING_SSH_KEY }}
          script: |
            cd /opt/app
            export TAG=${{ inputs.image_tag }}
            docker compose -f docker-compose.prod.yml pull
            docker compose -f docker-compose.prod.yml up -d --remove-orphans

      - name: Notify Rollback
        run: |
          curl -X POST "${{ secrets.SLACK_WEBHOOK_URL }}" \
            -H 'Content-type: application/json' \
            -d '{
              "text": "ROLLBACK executed on ${{ inputs.environment }}",
              "blocks": [
                {
                  "type": "section",
                  "text": {
                    "type": "mrkdwn",
                    "text": "*ROLLBACK: ${{ inputs.environment }}*\nMethod: ${{ inputs.rollback_type }}\nActor: ${{ github.actor }}\nReason: Manual trigger"
                  }
                }
              ]
            }'
```

---

## Notification Setup

### Slack Integration

```yaml
# Reusable notification step
# Usage: include in any workflow's final job

- name: Send Slack Notification
  if: always()
  env:
    SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
    STATUS: ${{ job.status }}
    WORKFLOW: ${{ github.workflow }}
    ACTOR: ${{ github.actor }}
    REF: ${{ github.ref_name }}
    SHA: ${{ github.sha }}
    RUN_URL: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
  run: |
    if [ "$STATUS" = "success" ]; then
      EMOJI=":white_check_mark:"
      COLOR="#36a64f"
    elif [ "$STATUS" = "failure" ]; then
      EMOJI=":x:"
      COLOR="#dc3545"
    else
      EMOJI=":warning:"
      COLOR="#ffc107"
    fi

    curl -X POST "$SLACK_WEBHOOK_URL" \
      -H 'Content-type: application/json' \
      -d "{
        \"attachments\": [{
          \"color\": \"$COLOR\",
          \"blocks\": [
            {
              \"type\": \"section\",
              \"text\": {
                \"type\": \"mrkdwn\",
                \"text\": \"$EMOJI *$WORKFLOW* — $STATUS\n*Branch:* $REF\n*Commit:* \`${SHA:0:7}\`\n*Actor:* $ACTOR\n<$RUN_URL|View Run>\"
              }
            }
          ]
        }]
      }"
```

### GitHub Actions Summary

```yaml
# Add a summary to every workflow for quick visibility
- name: Job Summary
  if: always()
  run: |
    echo "## Deploy Summary" >> $GITHUB_STEP_SUMMARY
    echo "" >> $GITHUB_STEP_SUMMARY
    echo "| Item | Value |" >> $GITHUB_STEP_SUMMARY
    echo "|------|-------|" >> $GITHUB_STEP_SUMMARY
    echo "| Environment | ${{ inputs.environment || 'staging' }} |" >> $GITHUB_STEP_SUMMARY
    echo "| Image Tag | \`${{ env.TAG }}\` |" >> $GITHUB_STEP_SUMMARY
    echo "| Commit | \`${{ github.sha }}\` |" >> $GITHUB_STEP_SUMMARY
    echo "| Status | ${{ job.status }} |" >> $GITHUB_STEP_SUMMARY
    echo "| Actor | ${{ github.actor }} |" >> $GITHUB_STEP_SUMMARY
```
