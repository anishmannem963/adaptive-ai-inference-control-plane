# Adaptive AI Inference Control Plane

An evidence-driven platform for cost-, latency-, quality-, and health-aware routing across AI inference backends.

## Status

Iteration 4 adds provider-aware exact-response caching, Redis-backed retry idempotency, cache telemetry, and fail-open cache isolation. Aggregate cost, latency, and recovery claims remain pending until the repeated benchmark and fault matrices are complete.

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
- cache hit, miss, write, replay, conflict, and backend-error telemetry
- AWS disabled by default with fail-closed budget configuration

## Reliability behavior

Auto-routed requests can try each eligible provider at most once. A failed provider is excluded before the request is rerouted. Explicit model requests never fall back to a different model.

Open circuits reject traffic until their recovery interval passes. Exactly one request is then permitted as a half-open recovery probe. Success closes the circuit; failure reopens it.

Redis accelerates repeated requests but is not on the inference availability path. A cache read or write failure is recorded and the gateway continues through normal provider execution.

Inspect runtime state:

~~~bash
curl http://localhost:8080/v1/providers/health
curl http://localhost:8080/v1/cache/status
~~~

A completion response identifies every attempted provider, fallback count, and whether the selected result was served from cache. The `X-Cache` response header reports `MISS`, `HIT`, `REPLAY`, or `BYPASS` when response caching is disabled.

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

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `CACHE_ENABLED` | `true` | Enables exact-response caching |
| `REDIS_URL` | empty | Uses Redis when set; otherwise uses memory |
| `CACHE_TTL_SECONDS` | `300` | Exact-response cache lifetime |
| `IDEMPOTENCY_TTL_SECONDS` | `86400` | Retry record lifetime |

## Evidence policy

Mock-provider prices, quality scores, latency, and failures are controlled simulation inputs. No production performance, cost-reduction, recovery-time, vLLM, Bedrock, or Kubernetes claim will be published until repeated experiments retain machine-readable evidence.

## Roadmap

1. Safe service foundation — complete
2. OpenAI-compatible gateway and deterministic providers — complete
3. Adaptive constraint-aware routing — complete
4. Provider isolation, circuit breaking, admission control, and fallback — complete
5. Redis caching and retry idempotency — complete
6. Metrics, tracing, and observability dashboard
7. Local and cloud model adapters
8. Kubernetes, Helm, and Terraform
9. Repeated benchmarks and fault injection
10. Controlled cloud validation and v1.0 release

## License

MIT
