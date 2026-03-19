# Monitoring Reference — Logging, Error Tracking, APM, Metrics, Alerting

> Read this file when setting up observability, configuring logging, integrating
> error tracking, or building dashboards for the application.

---

## Table of Contents
1. [Logging](#logging)
2. [Error Tracking (Sentry)](#error-tracking-sentry)
3. [APM and Distributed Tracing (OpenTelemetry)](#apm-and-distributed-tracing-opentelemetry)
4. [Metrics (Prometheus)](#metrics-prometheus)
5. [Dashboards (Grafana)](#dashboards-grafana)
6. [Alerting](#alerting)
7. [BullMQ Monitoring](#bullmq-monitoring)
8. [Health Check Endpoint](#health-check-endpoint)

---

## Logging

### Stack: pino + nestjs-pino

Structured JSON logging with automatic request context. Every log line is machine-parseable.

### Installation

```bash
npm install pino nestjs-pino pino-http pino-pretty
```

### NestJS Logger Configuration

```typescript
// app.module.ts
import { LoggerModule } from 'nestjs-pino';

@Module({
  imports: [
    LoggerModule.forRootAsync({
      useFactory: (config: ConfigService) => ({
        pinoHttp: {
          level: config.get('LOG_LEVEL', 'info'),

          // Use pino-pretty only in development
          transport: config.get('NODE_ENV') === 'development'
            ? { target: 'pino-pretty', options: { colorize: true, singleLine: true } }
            : undefined,

          // Request ID correlation — trace a request across all log lines
          genReqId: (req) => req.headers['x-request-id'] || crypto.randomUUID(),

          // Custom serializers — strip sensitive data
          serializers: {
            req: (req) => ({
              id: req.id,
              method: req.method,
              url: req.url,
              // Never log: headers (may contain auth tokens), body (may contain PII)
            }),
            res: (res) => ({
              statusCode: res.statusCode,
            }),
          },

          // Redact sensitive fields if they appear in log context
          redact: {
            paths: [
              'req.headers.authorization',
              'req.headers.cookie',
              'password',
              'token',
              'secret',
              'creditCard',
              '*.password',
              '*.token',
              '*.secret',
            ],
            censor: '[REDACTED]',
          },

          // Custom log level based on status code
          customLogLevel: (req, res, err) => {
            if (res.statusCode >= 500 || err) return 'error';
            if (res.statusCode >= 400) return 'warn';
            return 'info';
          },

          // Attach tenant context to every log line
          customProps: (req) => ({
            tenantContext: req.tenantContext
              ? {
                  companyId: req.tenantContext.companyId,
                  workspaceId: req.tenantContext.workspaceId,
                  domainId: req.tenantContext.domainId,
                }
              : undefined,
          }),
        },
      }),
      inject: [ConfigService],
    }),
  ],
})
export class AppModule {}
```

### Log Levels Per Environment

| Environment | Level | What Gets Logged |
|-------------|-------|-----------------|
| Development | `debug` | Everything — debug, info, warn, error, fatal |
| Test | `warn` | Only warnings and errors — keep test output clean |
| Staging | `info` | Info and above — request logs, business events |
| Production | `warn` | Warnings and errors only — minimize volume and cost |

### Structured Log Format (Production)

```json
{
  "level": 30,
  "time": 1710000000000,
  "pid": 1,
  "hostname": "api-7f8b9c-abcde",
  "req": { "id": "550e8400-e29b-41d4-a716-446655440000", "method": "POST", "url": "/domains/abc/recipients" },
  "res": { "statusCode": 201 },
  "responseTime": 45,
  "tenantContext": {
    "companyId": "company-123",
    "workspaceId": "workspace-456",
    "domainId": "domain-789"
  },
  "msg": "request completed"
}
```

### Logging Rules

| Rule | Why |
|------|-----|
| Never log PII (email, name, phone) | GDPR/compliance — PII in logs is a data breach |
| Never log auth tokens or passwords | Secrets in logs are a security vulnerability |
| Always include request ID | Correlate logs across services for a single request |
| Always include tenant context | Filter logs by company/workspace/domain for support |
| Use structured fields, not string interpolation | `log.info({ userId, action }, 'user action')` not `log.info(\`User ${userId} did ${action}\`)` |
| Log at the right level | debug=development, info=business events, warn=recoverable issues, error=failures |
| Never log in hot loops | Logging in a loop processing 10k recipients = 10k log entries = outage |

### Logger Usage in Services

```typescript
import { Logger } from '@nestjs/common';

@Injectable()
export class RecipientService {
  private readonly logger = new Logger(RecipientService.name);

  async importRecipients(domainId: string, rows: ImportRow[]) {
    // INFO: business event
    this.logger.log({
      msg: 'Starting recipient import',
      domainId,
      rowCount: rows.length,
    });

    try {
      const result = await this.repo.bulkInsert(domainId, rows);

      // INFO: successful outcome
      this.logger.log({
        msg: 'Recipient import completed',
        domainId,
        imported: result.inserted,
        skipped: result.skipped,
        duration: result.durationMs,
      });

      return result;
    } catch (error) {
      // ERROR: failure with context
      this.logger.error({
        msg: 'Recipient import failed',
        domainId,
        rowCount: rows.length,
        error: error.message,
        stack: error.stack,
      });
      throw error;
    }
  }
}
```

---

## Error Tracking (Sentry)

### Installation

```bash
# Backend
npm install @sentry/nestjs @sentry/profiling-node

# Frontend
npm install @sentry/nextjs
```

### NestJS Sentry Setup

```typescript
// instrument.ts — must be imported FIRST, before any other imports
import * as Sentry from '@sentry/nestjs';
import { nodeProfilingIntegration } from '@sentry/profiling-node';

Sentry.init({
  dsn: process.env.SENTRY_DSN,
  environment: process.env.SENTRY_ENVIRONMENT || process.env.NODE_ENV,
  release: process.env.npm_package_version || 'unknown',

  // Performance monitoring
  tracesSampleRate: process.env.NODE_ENV === 'production' ? 0.1 : 1.0,
  profilesSampleRate: process.env.NODE_ENV === 'production' ? 0.1 : 1.0,

  integrations: [
    nodeProfilingIntegration(),
  ],

  // Filter out noisy errors
  ignoreErrors: [
    'NotFoundException',           // 404s are expected
    'UnauthorizedException',       // 401s are expected
    'BadRequestException',         // 400s are validation errors
  ],

  // Strip PII from error reports
  beforeSend(event) {
    // Remove user IP addresses
    if (event.user) {
      delete event.user.ip_address;
    }

    // Remove sensitive headers
    if (event.request?.headers) {
      delete event.request.headers.authorization;
      delete event.request.headers.cookie;
    }

    return event;
  },

  // Add tenant context to every error
  beforeSendTransaction(event) {
    return event;
  },
});

// main.ts
import './instrument'; // MUST be first import
import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';
```

### Sentry Error Context Enrichment

```typescript
// sentry-context.interceptor.ts
import * as Sentry from '@sentry/nestjs';

@Injectable()
export class SentryContextInterceptor implements NestInterceptor {
  intercept(context: ExecutionContext, next: CallHandler): Observable<any> {
    const req = context.switchToHttp().getRequest();

    // Add tenant context as tags (filterable in Sentry UI)
    if (req.tenantContext) {
      Sentry.setTag('company_id', req.tenantContext.companyId);
      Sentry.setTag('workspace_id', req.tenantContext.workspaceId);
      Sentry.setTag('domain_id', req.tenantContext.domainId);
      Sentry.setTag('subscription_tier', req.tenantContext.subscriptionTier);
    }

    // Add user context
    if (req.user) {
      Sentry.setUser({
        id: req.user.id,
        // Never send email or username to Sentry — PII compliance
      });
    }

    return next.handle();
  }
}
```

### Next.js Sentry Setup

```typescript
// sentry.client.config.ts
import * as Sentry from '@sentry/nextjs';

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT,
  tracesSampleRate: 0.1,
  replaysSessionSampleRate: 0.01,
  replaysOnErrorSampleRate: 1.0,

  integrations: [
    Sentry.replayIntegration({
      // Mask all text and block all media for PII compliance
      maskAllText: true,
      blockAllMedia: true,
    }),
  ],
});
```

### Source Maps Upload in CI

```yaml
# In GitHub Actions deploy workflow
- name: Upload Source Maps to Sentry
  env:
    SENTRY_AUTH_TOKEN: ${{ secrets.SENTRY_AUTH_TOKEN }}
    SENTRY_ORG: ${{ secrets.SENTRY_ORG }}
  run: |
    # API source maps
    npx sentry-cli releases files "${{ env.TAG }}" upload-sourcemaps \
      ./apps/api/dist \
      --url-prefix '~/dist' \
      --project ${{ secrets.SENTRY_PROJECT_API }}

    # Frontend source maps
    npx sentry-cli releases files "${{ env.TAG }}" upload-sourcemaps \
      ./apps/web/.next \
      --url-prefix '~/_next' \
      --project ${{ secrets.SENTRY_PROJECT_WEB }}

    # Finalize release
    npx sentry-cli releases finalize "${{ env.TAG }}"
```

---

## APM and Distributed Tracing (OpenTelemetry)

### Installation

```bash
npm install @opentelemetry/sdk-node \
  @opentelemetry/api \
  @opentelemetry/auto-instrumentations-node \
  @opentelemetry/exporter-trace-otlp-http \
  @opentelemetry/exporter-metrics-otlp-http \
  @opentelemetry/resources \
  @opentelemetry/semantic-conventions
```

### OpenTelemetry Setup

```typescript
// tracing.ts — import before everything else (after Sentry instrument.ts)
import { NodeSDK } from '@opentelemetry/sdk-node';
import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { OTLPMetricExporter } from '@opentelemetry/exporter-metrics-otlp-http';
import { PeriodicExportingMetricReader } from '@opentelemetry/sdk-metrics';
import { Resource } from '@opentelemetry/resources';
import { ATTR_SERVICE_NAME, ATTR_SERVICE_VERSION } from '@opentelemetry/semantic-conventions';

const sdk = new NodeSDK({
  resource: new Resource({
    [ATTR_SERVICE_NAME]: 'api',
    [ATTR_SERVICE_VERSION]: process.env.npm_package_version || 'unknown',
    'deployment.environment': process.env.NODE_ENV || 'development',
  }),

  traceExporter: new OTLPTraceExporter({
    // Jaeger for local dev, cloud collector for production
    url: process.env.OTEL_EXPORTER_OTLP_ENDPOINT || 'http://jaeger:4318/v1/traces',
  }),

  metricReader: new PeriodicExportingMetricReader({
    exporter: new OTLPMetricExporter({
      url: process.env.OTEL_EXPORTER_METRICS_ENDPOINT || 'http://prometheus:4318/v1/metrics',
    }),
    exportIntervalMillis: 15000,
  }),

  instrumentations: [
    getNodeAutoInstrumentations({
      // Instrument HTTP, Express, pg, ioredis automatically
      '@opentelemetry/instrumentation-http': { enabled: true },
      '@opentelemetry/instrumentation-express': { enabled: true },
      '@opentelemetry/instrumentation-pg': { enabled: true },
      '@opentelemetry/instrumentation-ioredis': { enabled: true },
      // Disable noisy instrumentations
      '@opentelemetry/instrumentation-fs': { enabled: false },
      '@opentelemetry/instrumentation-dns': { enabled: false },
    }),
  ],
});

sdk.start();

// Graceful shutdown
process.on('SIGTERM', () => {
  sdk.shutdown()
    .then(() => console.log('Tracing terminated'))
    .catch((error) => console.error('Error terminating tracing', error))
    .finally(() => process.exit(0));
});
```

### Custom Span for Business Operations

```typescript
import { trace, SpanStatusCode } from '@opentelemetry/api';

const tracer = trace.getTracer('recipient-service');

@Injectable()
export class RecipientService {
  async importRecipients(domainId: string, rows: ImportRow[]) {
    return tracer.startActiveSpan('recipient.import', async (span) => {
      span.setAttributes({
        'tenant.domain_id': domainId,
        'import.row_count': rows.length,
      });

      try {
        const result = await this.repo.bulkInsert(domainId, rows);
        span.setAttributes({
          'import.inserted': result.inserted,
          'import.skipped': result.skipped,
        });
        span.setStatus({ code: SpanStatusCode.OK });
        return result;
      } catch (error) {
        span.setStatus({ code: SpanStatusCode.ERROR, message: error.message });
        span.recordException(error);
        throw error;
      } finally {
        span.end();
      }
    });
  }
}
```

### Jaeger for Local Development

```yaml
# Included in docker-compose.yml (dev)
jaeger:
  image: jaegertracing/all-in-one:latest
  ports:
    - "16686:16686"  # Jaeger UI — open in browser
    - "4318:4318"    # OTLP HTTP receiver
  environment:
    COLLECTOR_OTLP_ENABLED: "true"

# Access: http://localhost:16686
# Search by service name: "api"
# Filter by tenant: tag "tenant.domain_id"
```

---

## Metrics (Prometheus)

### NestJS Prometheus Metrics Endpoint

```typescript
// metrics/metrics.module.ts
import { PrometheusModule } from '@willsoto/nestjs-prometheus';

@Module({
  imports: [
    PrometheusModule.register({
      path: '/metrics',
      defaultMetrics: {
        enabled: true,
        config: {
          prefix: 'sb_',  // second brain prefix
        },
      },
    }),
  ],
})
export class MetricsModule {}
```

### Custom Metrics

```typescript
// metrics/custom-metrics.service.ts
import { Injectable } from '@nestjs/common';
import { InjectMetric } from '@willsoto/nestjs-prometheus';
import { Counter, Histogram, Gauge } from 'prom-client';

@Injectable()
export class CustomMetricsService {
  constructor(
    // Request latency by endpoint and status
    @InjectMetric('sb_http_request_duration_seconds')
    public readonly httpRequestDuration: Histogram<string>,

    // Total requests by endpoint, method, and status
    @InjectMetric('sb_http_requests_total')
    public readonly httpRequestsTotal: Counter<string>,

    // BullMQ queue depth
    @InjectMetric('sb_queue_depth')
    public readonly queueDepth: Gauge<string>,

    // BullMQ active jobs
    @InjectMetric('sb_queue_active_jobs')
    public readonly activeJobs: Gauge<string>,

    // BullMQ completed jobs total
    @InjectMetric('sb_queue_completed_total')
    public readonly completedJobs: Counter<string>,

    // BullMQ failed jobs total
    @InjectMetric('sb_queue_failed_total')
    public readonly failedJobs: Counter<string>,

    // Redis cache hit/miss
    @InjectMetric('sb_cache_hits_total')
    public readonly cacheHits: Counter<string>,

    @InjectMetric('sb_cache_misses_total')
    public readonly cacheMisses: Counter<string>,

    // Database connection pool
    @InjectMetric('sb_db_pool_active_connections')
    public readonly dbPoolActive: Gauge<string>,

    @InjectMetric('sb_db_pool_idle_connections')
    public readonly dbPoolIdle: Gauge<string>,

    // Per-workspace metrics for MSSP
    @InjectMetric('sb_workspace_recipients_total')
    public readonly workspaceRecipients: Gauge<string>,
  ) {}
}

// metrics/metric-definitions.provider.ts
import { makeCounterProvider, makeHistogramProvider, makeGaugeProvider } from '@willsoto/nestjs-prometheus';

export const metricProviders = [
  makeHistogramProvider({
    name: 'sb_http_request_duration_seconds',
    help: 'HTTP request duration in seconds',
    labelNames: ['method', 'route', 'status_code'],
    buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
  }),
  makeCounterProvider({
    name: 'sb_http_requests_total',
    help: 'Total HTTP requests',
    labelNames: ['method', 'route', 'status_code'],
  }),
  makeGaugeProvider({
    name: 'sb_queue_depth',
    help: 'Number of jobs waiting in queue',
    labelNames: ['queue_name'],
  }),
  makeGaugeProvider({
    name: 'sb_queue_active_jobs',
    help: 'Number of currently active jobs',
    labelNames: ['queue_name'],
  }),
  makeCounterProvider({
    name: 'sb_queue_completed_total',
    help: 'Total completed jobs',
    labelNames: ['queue_name'],
  }),
  makeCounterProvider({
    name: 'sb_queue_failed_total',
    help: 'Total failed jobs',
    labelNames: ['queue_name'],
  }),
  makeCounterProvider({
    name: 'sb_cache_hits_total',
    help: 'Total cache hits',
    labelNames: ['cache_name'],
  }),
  makeCounterProvider({
    name: 'sb_cache_misses_total',
    help: 'Total cache misses',
    labelNames: ['cache_name'],
  }),
  makeGaugeProvider({
    name: 'sb_db_pool_active_connections',
    help: 'Active database connections',
    labelNames: [],
  }),
  makeGaugeProvider({
    name: 'sb_db_pool_idle_connections',
    help: 'Idle database connections',
    labelNames: [],
  }),
  makeGaugeProvider({
    name: 'sb_workspace_recipients_total',
    help: 'Total recipients per workspace (MSSP metric)',
    labelNames: ['workspace_id', 'company_id'],
  }),
];
```

### Metrics Interceptor (Auto-Record Request Metrics)

```typescript
// metrics/metrics.interceptor.ts
@Injectable()
export class MetricsInterceptor implements NestInterceptor {
  constructor(private readonly metrics: CustomMetricsService) {}

  intercept(context: ExecutionContext, next: CallHandler): Observable<any> {
    const req = context.switchToHttp().getRequest();
    const res = context.switchToHttp().getResponse();
    const start = Date.now();

    return next.handle().pipe(
      tap(() => {
        const duration = (Date.now() - start) / 1000;
        const route = req.route?.path || req.url;

        this.metrics.httpRequestDuration.observe(
          { method: req.method, route, status_code: res.statusCode },
          duration,
        );
        this.metrics.httpRequestsTotal.inc(
          { method: req.method, route, status_code: res.statusCode },
        );
      }),
      catchError((error) => {
        const duration = (Date.now() - start) / 1000;
        const route = req.route?.path || req.url;
        const statusCode = error.status || 500;

        this.metrics.httpRequestDuration.observe(
          { method: req.method, route, status_code: statusCode },
          duration,
        );
        this.metrics.httpRequestsTotal.inc(
          { method: req.method, route, status_code: statusCode },
        );

        throw error;
      }),
    );
  }
}
```

### Queue Metrics Collector (Runs on Interval)

```typescript
// metrics/queue-metrics.collector.ts
@Injectable()
export class QueueMetricsCollector {
  constructor(
    private readonly metrics: CustomMetricsService,
    @InjectQueue('import') private importQueue: Queue,
    @InjectQueue('bulk-operations') private bulkQueue: Queue,
    @InjectQueue('email-send') private emailQueue: Queue,
  ) {}

  @Interval(15000) // Collect every 15 seconds
  async collectQueueMetrics() {
    const queues = [
      { name: 'import', queue: this.importQueue },
      { name: 'bulk-operations', queue: this.bulkQueue },
      { name: 'email-send', queue: this.emailQueue },
    ];

    for (const { name, queue } of queues) {
      const counts = await queue.getJobCounts();
      this.metrics.queueDepth.set({ queue_name: name }, counts.waiting + counts.delayed);
      this.metrics.activeJobs.set({ queue_name: name }, counts.active);
    }
  }
}
```

### Prometheus Scrape Configuration

```yaml
# prometheus/prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'nestjs-api'
    metrics_path: /metrics
    static_configs:
      - targets: ['api:3001']
    # For multiple API replicas, use DNS-based service discovery:
    # dns_sd_configs:
    #   - names: ['api']
    #     type: A
    #     port: 3001

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']

  - job_name: 'postgres-exporter'
    static_configs:
      - targets: ['postgres-exporter:9187']

  - job_name: 'redis-exporter'
    static_configs:
      - targets: ['redis-exporter:9121']
```

---

## Dashboards (Grafana)

### API Latency Dashboard

```json
{
  "title": "API Latency",
  "panels": [
    {
      "title": "Request Latency P50/P95/P99",
      "type": "timeseries",
      "targets": [
        {
          "expr": "histogram_quantile(0.50, rate(sb_http_request_duration_seconds_bucket[5m]))",
          "legendFormat": "p50"
        },
        {
          "expr": "histogram_quantile(0.95, rate(sb_http_request_duration_seconds_bucket[5m]))",
          "legendFormat": "p95"
        },
        {
          "expr": "histogram_quantile(0.99, rate(sb_http_request_duration_seconds_bucket[5m]))",
          "legendFormat": "p99"
        }
      ]
    },
    {
      "title": "Request Rate by Status Code",
      "type": "timeseries",
      "targets": [
        {
          "expr": "sum(rate(sb_http_requests_total[5m])) by (status_code)",
          "legendFormat": "{{status_code}}"
        }
      ]
    },
    {
      "title": "Error Rate (5xx)",
      "type": "stat",
      "targets": [
        {
          "expr": "sum(rate(sb_http_requests_total{status_code=~\"5..\"}[5m])) / sum(rate(sb_http_requests_total[5m])) * 100",
          "legendFormat": "Error %"
        }
      ],
      "thresholds": {
        "steps": [
          { "value": 0, "color": "green" },
          { "value": 0.5, "color": "yellow" },
          { "value": 1, "color": "red" }
        ]
      }
    },
    {
      "title": "Slowest Endpoints (P99)",
      "type": "table",
      "targets": [
        {
          "expr": "topk(10, histogram_quantile(0.99, sum(rate(sb_http_request_duration_seconds_bucket[5m])) by (le, route)))",
          "format": "table"
        }
      ]
    }
  ]
}
```

### Queue Health Dashboard

```json
{
  "title": "Queue Health",
  "panels": [
    {
      "title": "Queue Depth (Waiting + Delayed)",
      "type": "timeseries",
      "targets": [
        {
          "expr": "sb_queue_depth",
          "legendFormat": "{{queue_name}}"
        }
      ]
    },
    {
      "title": "Active Jobs",
      "type": "timeseries",
      "targets": [
        {
          "expr": "sb_queue_active_jobs",
          "legendFormat": "{{queue_name}}"
        }
      ]
    },
    {
      "title": "Job Completion Rate (per minute)",
      "type": "timeseries",
      "targets": [
        {
          "expr": "rate(sb_queue_completed_total[1m]) * 60",
          "legendFormat": "{{queue_name}} completed"
        },
        {
          "expr": "rate(sb_queue_failed_total[1m]) * 60",
          "legendFormat": "{{queue_name}} failed"
        }
      ]
    },
    {
      "title": "Job Failure Rate",
      "type": "stat",
      "targets": [
        {
          "expr": "sum(rate(sb_queue_failed_total[5m])) / (sum(rate(sb_queue_completed_total[5m])) + sum(rate(sb_queue_failed_total[5m]))) * 100",
          "legendFormat": "Failure %"
        }
      ],
      "thresholds": {
        "steps": [
          { "value": 0, "color": "green" },
          { "value": 1, "color": "yellow" },
          { "value": 5, "color": "red" }
        ]
      }
    }
  ]
}
```

### Database Connections Dashboard

```json
{
  "title": "Database Health",
  "panels": [
    {
      "title": "Connection Pool Usage",
      "type": "timeseries",
      "targets": [
        {
          "expr": "sb_db_pool_active_connections",
          "legendFormat": "Active"
        },
        {
          "expr": "sb_db_pool_idle_connections",
          "legendFormat": "Idle"
        }
      ]
    },
    {
      "title": "PostgreSQL Queries per Second",
      "type": "timeseries",
      "targets": [
        {
          "expr": "rate(pg_stat_database_xact_commit{datname=\"secondbrain\"}[5m])",
          "legendFormat": "Commits/s"
        }
      ]
    },
    {
      "title": "Database Size",
      "type": "stat",
      "targets": [
        {
          "expr": "pg_database_size_bytes{datname=\"secondbrain\"} / 1024 / 1024 / 1024",
          "legendFormat": "Size (GB)"
        }
      ]
    }
  ]
}
```

---

## Alerting

### Alert Rules (Prometheus Alertmanager)

```yaml
# alertmanager/alert-rules.yml
groups:
  - name: api-alerts
    rules:
      # 5xx spike — more than 1% error rate for 5 minutes
      - alert: HighErrorRate
        expr: >
          sum(rate(sb_http_requests_total{status_code=~"5.."}[5m]))
          / sum(rate(sb_http_requests_total[5m])) > 0.01
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High 5xx error rate: {{ $value | humanizePercentage }}"
          description: "API error rate has been above 1% for 5 minutes."

      # Latency spike — P99 above 5 seconds for 5 minutes
      - alert: HighLatency
        expr: >
          histogram_quantile(0.99, rate(sb_http_request_duration_seconds_bucket[5m])) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High P99 latency: {{ $value | humanizeDuration }}"
          description: "API P99 latency has been above 5 seconds for 5 minutes."

  - name: queue-alerts
    rules:
      # Queue backup — more than 1000 jobs waiting for 10 minutes
      - alert: QueueBackup
        expr: sb_queue_depth > 1000
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Queue backup: {{ $labels.queue_name }} has {{ $value }} waiting jobs"
          description: "Queue {{ $labels.queue_name }} has had >1000 waiting jobs for 10 minutes."

      # Dead letter queue growth — any failed jobs accumulating
      - alert: FailedJobsAccumulating
        expr: rate(sb_queue_failed_total[15m]) > 0.1
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Failed jobs accumulating in {{ $labels.queue_name }}"
          description: "Queue {{ $labels.queue_name }} is consistently producing failed jobs."

  - name: database-alerts
    rules:
      # Connection pool exhaustion — more than 80% of pool in use
      - alert: DatabaseConnectionPoolHigh
        expr: >
          sb_db_pool_active_connections
          / (sb_db_pool_active_connections + sb_db_pool_idle_connections) > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Database connection pool at {{ $value | humanizePercentage }}"
          description: "Connection pool utilization has been above 80% for 5 minutes."

      # Connection pool exhaustion — 95% in use (critical)
      - alert: DatabaseConnectionPoolCritical
        expr: >
          sb_db_pool_active_connections
          / (sb_db_pool_active_connections + sb_db_pool_idle_connections) > 0.95
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Database connection pool nearly exhausted: {{ $value | humanizePercentage }}"
          description: "Connection pool utilization above 95%. Imminent request failures."

  - name: redis-alerts
    rules:
      # Redis memory high — above 80% of maxmemory
      - alert: RedisMemoryHigh
        expr: redis_memory_used_bytes / redis_memory_max_bytes > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Redis memory at {{ $value | humanizePercentage }}"
          description: "Redis memory usage above 80%. Evictions may occur."

      # Redis memory critical — above 95%
      - alert: RedisMemoryCritical
        expr: redis_memory_used_bytes / redis_memory_max_bytes > 0.95
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Redis memory critical: {{ $value | humanizePercentage }}"
          description: "Redis memory above 95%. Active evictions or OOM imminent."

  - name: health-alerts
    rules:
      # Health check failing
      - alert: HealthCheckFailing
        expr: up{job="nestjs-api"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "API health check failing"
          description: "NestJS API has been unreachable for 1 minute."
```

### Alertmanager Notification Config

```yaml
# alertmanager/alertmanager.yml
route:
  receiver: 'default'
  group_by: ['alertname', 'severity']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - match:
        severity: critical
      receiver: 'critical-channel'
      repeat_interval: 1h

receivers:
  - name: 'default'
    slack_configs:
      - api_url: 'SLACK_WEBHOOK_URL'
        channel: '#alerts'
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'

  - name: 'critical-channel'
    slack_configs:
      - api_url: 'SLACK_WEBHOOK_URL'
        channel: '#alerts-critical'
        title: 'CRITICAL: {{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'
    # Also page on-call via PagerDuty/Opsgenie for critical alerts
    # pagerduty_configs:
    #   - service_key: 'PAGERDUTY_SERVICE_KEY'
```

---

## BullMQ Monitoring

### Bull Board Setup

```typescript
// bull-board/bull-board.module.ts
import { BullBoardModule } from '@bull-board/nestjs';
import { ExpressAdapter } from '@bull-board/express';
import { BullMQAdapter } from '@bull-board/api/bullMQAdapter';

@Module({
  imports: [
    BullBoardModule.forRoot({
      route: '/queues',
      adapter: ExpressAdapter,
    }),
    BullBoardModule.forFeature({
      name: 'import',
      adapter: BullMQAdapter,
    }),
    BullBoardModule.forFeature({
      name: 'bulk-operations',
      adapter: BullMQAdapter,
    }),
    BullBoardModule.forFeature({
      name: 'email-send',
      adapter: BullMQAdapter,
    }),
    BullBoardModule.forFeature({
      name: 'notifications',
      adapter: BullMQAdapter,
    }),
  ],
})
export class BullBoardSetupModule {}
```

### Bull Board Access Control

```typescript
// bull-board/bull-board.guard.ts — restrict access in production
@Injectable()
export class BullBoardGuard implements CanActivate {
  constructor(private readonly config: ConfigService) {}

  canActivate(context: ExecutionContext): boolean {
    const req = context.switchToHttp().getRequest();

    // In development, always allow
    if (this.config.get('NODE_ENV') === 'development') return true;

    // In production, require admin token
    const token = req.headers['x-admin-token'];
    return token === this.config.get('ADMIN_BULL_BOARD_TOKEN');
  }
}
```

### Dead Letter Queue (DLQ) Monitoring

```typescript
// monitoring/dlq-monitor.service.ts
@Injectable()
export class DLQMonitorService {
  private readonly logger = new Logger(DLQMonitorService.name);

  constructor(
    @InjectQueue('import') private importQueue: Queue,
    @InjectQueue('bulk-operations') private bulkQueue: Queue,
    private readonly metrics: CustomMetricsService,
  ) {}

  @Interval(60000) // Check every minute
  async checkDeadLetterQueues() {
    const queues = [
      { name: 'import', queue: this.importQueue },
      { name: 'bulk-operations', queue: this.bulkQueue },
    ];

    for (const { name, queue } of queues) {
      const failedCount = await queue.getFailedCount();

      if (failedCount > 0) {
        const failedJobs = await queue.getFailed(0, 10);

        this.logger.warn({
          msg: 'Failed jobs detected',
          queue: name,
          failedCount,
          recentFailures: failedJobs.map((job) => ({
            id: job.id,
            name: job.name,
            failedReason: job.failedReason,
            attemptsMade: job.attemptsMade,
            timestamp: job.timestamp,
          })),
        });
      }
    }
  }

  // Manual retry for failed jobs (admin action)
  async retryFailedJobs(queueName: string, maxRetries: number = 50): Promise<{ retried: number }> {
    const queue = this.getQueue(queueName);
    const failedJobs = await queue.getFailed(0, maxRetries);

    let retried = 0;
    for (const job of failedJobs) {
      await job.retry();
      retried++;
    }

    this.logger.log({
      msg: 'Retried failed jobs',
      queue: queueName,
      retried,
    });

    return { retried };
  }

  private getQueue(name: string): Queue {
    const map: Record<string, Queue> = {
      import: this.importQueue,
      'bulk-operations': this.bulkQueue,
    };
    if (!map[name]) throw new Error(`Unknown queue: ${name}`);
    return map[name];
  }
}
```

### Job Completion Rate Tracking

```typescript
// monitoring/job-metrics.listener.ts
import { OnQueueEvent, QueueEventsHost, QueueEventsListener } from '@nestjs/bullmq';

@QueueEventsListener('import')
export class ImportJobMetrics extends QueueEventsHost {
  constructor(private readonly metrics: CustomMetricsService) {
    super();
  }

  @OnQueueEvent('completed')
  onCompleted() {
    this.metrics.completedJobs.inc({ queue_name: 'import' });
  }

  @OnQueueEvent('failed')
  onFailed() {
    this.metrics.failedJobs.inc({ queue_name: 'import' });
  }
}
```

---

## Health Check Endpoint

### Full Health Check Pattern

The `/health` endpoint returns the aggregate status of all dependencies.

```typescript
// Response when healthy:
// GET /health → 200
{
  "status": "ok",
  "info": {
    "api": { "status": "up" },
    "database": { "status": "up", "responseTime": 12 },
    "redis": { "status": "up", "responseTime": 2 },
    "bullmq": { "status": "up", "activeJobs": 3, "waitingJobs": 12, "failedJobs": 0 }
  },
  "error": {},
  "details": {
    "api": { "status": "up" },
    "database": { "status": "up", "responseTime": 12 },
    "redis": { "status": "up", "responseTime": 2 },
    "bullmq": { "status": "up", "activeJobs": 3, "waitingJobs": 12, "failedJobs": 0 }
  }
}

// Response when degraded:
// GET /health → 503
{
  "status": "error",
  "info": {
    "api": { "status": "up" },
    "redis": { "status": "up", "responseTime": 2 }
  },
  "error": {
    "database": { "status": "down", "error": "Connection refused" }
  },
  "details": {
    "api": { "status": "up" },
    "database": { "status": "down", "error": "Connection refused" },
    "redis": { "status": "up", "responseTime": 2 }
  }
}
```

### Liveness vs Readiness vs Startup Probes

| Probe | Path | Purpose | Action on Failure |
|-------|------|---------|-------------------|
| Startup | `/health/live` | Is the process starting? | Keep waiting (don't restart yet) |
| Liveness | `/health/live` | Is the process alive? | Restart the container |
| Readiness | `/health/ready` | Can the process serve traffic? | Remove from load balancer |

```typescript
// GET /health/live → always 200 if process is running (no dependency checks)
@Get('live')
live() {
  return { status: 'ok', timestamp: new Date().toISOString() };
}

// GET /health/ready → 200 only if all dependencies are reachable
@Get('ready')
@HealthCheck()
async ready() {
  return this.health.check([
    () => this.db.pingCheck('database', { timeout: 1000 }),
    () => this.redis.pingCheck('redis', { timeout: 500 }),
  ]);
}

// GET /health → full status with details (for monitoring dashboards)
@Get()
@HealthCheck()
async check() {
  return this.health.check([
    () => this.db.pingCheck('database', { timeout: 3000 }),
    () => this.redis.pingCheck('redis', { timeout: 1000 }),
    () => this.bullmq.check('bullmq', { timeout: 2000 }),
  ]);
}
```

### Container Orchestrator Configuration

```yaml
# Kubernetes-style probe configuration (also works as docker healthcheck reference)
livenessProbe:
  httpGet:
    path: /health/live
    port: 3001
  initialDelaySeconds: 10
  periodSeconds: 10
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /health/ready
    port: 3001
  initialDelaySeconds: 15
  periodSeconds: 5
  failureThreshold: 3

startupProbe:
  httpGet:
    path: /health/live
    port: 3001
  initialDelaySeconds: 5
  periodSeconds: 5
  failureThreshold: 30   # 30 * 5s = 150s max startup time
```
