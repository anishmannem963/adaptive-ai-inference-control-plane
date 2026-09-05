# Adaptive AI Inference Control Plane

An evidence-driven platform for cost-, latency-, quality-, and health-aware routing across AI inference backends.

## Status

Iteration 5 adds Prometheus metrics, OpenTelemetry traces, a bounded telemetry API, and a Netlify-ready live observability dashboard. Aggregate cost, latency, and recovery claims remain pending until the repeated benchmark and fault matrices are complete.

## Implemented

- OpenAI-compatible typed inference gateway
- deterministic economy, fast, and quality provider profiles
- direct, single-provider, round-robin, lowest-cost, lowest-latency, highest-quality, and adaptive routing
- hard request-level cost, latency, and quality constraints
- explainable provider selection
- per-provider deadlines and runtime health accounting
- closed, open, and half-open circuit-breaker states
- single-flight recovery probes
- token-bucket admission limits
- concurrency bulkheads and immediate overload backpressure
- bounded automatic fallback for auto-routed requests
- no silent provider substitution for explicit-model requests
- provider-aware exact-response caching with configurable TTLs
- Redis-backed idempotent request replay and payload-conflict detection
- in-memory cache fallback for zero-cost local development
- fail-open cache behavior when Redis is unavailable
- Prometheus HTTP, inference, provider, latency, fallback, and estimated-cost metrics
- OpenTelemetry request and provider spans with optional OTLP/HTTP export
- trace IDs returned through `X-Trace-ID`
- bounded JSON telemetry summaries and recent routing events
- responsive static observability dashboard configured for Netlify
- AWS disabled by default with fail-closed budget configuration

## Reliability behavior

Auto-routed requests can try each eligible provider at most once. A failed provider is excluded before the request is rerouted. Explicit model requests never fall back to a different model.

Open circuits reject traffic until their recovery interval passes. Exactly one request is then permitted as a half-open recovery probe. Success closes the circuit; failure reopens it.

Redis accelerates repeated requests but is not on the inference availability path. A cache read or write failure is recorded and the gateway continues through normal provider execution.

A completion response identifies every attempted provider, fallback count, cache outcome, request ID, and distributed trace ID.

## Run locally

~~~bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn control_plane.main:app --reload --port 8080
~~~

Without `REDIS_URL`, the gateway uses a process-local TTL cache. For the Redis-backed configuration:

~~~bash
docker compose up --build
~~~

Adaptive request:

~~~bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "auto",
    "messages": [{"role": "user", "content": "Explain quorum."}],
    "routing": {
      "policy": "adaptive",
      "max_latency_ms": 200,
      "min_quality": 0.75
    }
  }'
~~~

Retry-safe request:

~~~bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Client-ID: interview-demo" \
  -H "X-Idempotency-Key: request-001" \
  -d '{
    "model": "mock-fast",
    "messages": [{"role": "user", "content": "Explain circuit breakers."}]
  }'
~~~

Repeating the same client ID, idempotency key, and payload returns the stored response. Reusing the key with a different payload returns HTTP 409. Both headers are required together.

## Observability

Prometheus exposition:

~~~bash
curl http://localhost:8080/metrics
~~~

Runtime JSON for the browser dashboard:

~~~bash
curl http://localhost:8080/v1/telemetry/summary
curl http://localhost:8080/v1/providers/health
curl http://localhost:8080/v1/cache/status
~~~

The metrics use bounded labels: provider, policy, cache status, HTTP method, known path, status, and outcome. Prompts, request IDs, client IDs, and idempotency keys are not Prometheus labels.

Every HTTP request creates an OpenTelemetry span. Provider execution creates a child span. Set `OTEL_EXPORTER_OTLP_ENDPOINT` to an OTLP/HTTP trace endpoint when a collector is available; leaving it empty keeps development completely local and free.

## Dashboard

The static dashboard is in `dashboard/`. Run it locally after starting the API:

~~~bash
python -m http.server 8888 --directory dashboard
~~~

Then open <http://localhost:8888>. The dashboard can:

- submit real inference requests through the adaptive router
- display the selected provider, cache outcome, fallback count, response, and trace ID
- poll current cache statistics and provider circuit health
- visualize recent request latency and per-provider success/failure totals
- show a bounded stream of recent routing events

The root `netlify.toml` sets `dashboard` as the publish directory. No Vercel configuration is required. When the API is deployed, set its `CORS_ALLOWED_ORIGINS` value to the exact Netlify site origin.

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `CACHE_ENABLED` | `true` | Enables exact-response caching |
| `REDIS_URL` | empty | Uses Redis when set; otherwise uses memory |
| `CACHE_TTL_SECONDS` | `300` | Exact-response cache lifetime |
| `IDEMPOTENCY_TTL_SECONDS` | `86400` | Retry record lifetime |
| `OTEL_SERVICE_NAME` | `adaptive-ai-inference-control-plane` | Trace service identity |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | empty | Optional OTLP/HTTP trace destination |
| `TELEMETRY_RECENT_EVENTS_LIMIT` | `100` | Maximum in-memory dashboard events |
| `CORS_ALLOWED_ORIGINS` | local dashboard origins | Comma-separated browser origins |

## Validation

~~~bash
ruff check .
ruff format --check .
mypy
pytest
python scripts/validate_dashboard.py
~~~

CI also starts a real Redis service and builds the production Docker image.

## Evidence policy

Mock-provider prices, quality scores, latency, and failures are controlled simulation inputs. No production performance, cost-reduction, recovery-time, vLLM, Bedrock, Kubernetes, or cloud-provider claim will be published until repeated experiments retain machine-readable evidence.

## Roadmap

1. Safe service foundation — complete
2. OpenAI-compatible gateway and deterministic providers — complete
3. Adaptive constraint-aware routing — complete
4. Provider isolation, circuit breaking, admission control, and fallback — complete
5. Redis caching and retry idempotency — complete
6. Metrics, tracing, and observability dashboard — complete
7. Local and cloud model adapters
8. Kubernetes, Helm, and Terraform
9. Repeated benchmarks and fault injection
10. Controlled cloud validation and v1.0 release

## License

MIT
