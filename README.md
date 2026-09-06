# Adaptive AI Inference Control Plane

An evidence-driven platform for cost-, latency-, quality-, and health-aware routing across AI inference backends.

## Status

Iteration 9 adds reproducible HTTP load benchmarks and repeated controlled provider-fault matrices. Pull requests run bounded versions; a manual evidence workflow retains the complete 12,000-request and 60-scenario JSON reports. Infrastructure remains plan-only, and no cloud resource is provisioned by CI.

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
- local Ollama chat inference through the native `/api/chat` API
- Amazon Bedrock inference through the model-independent Converse API
- exact Bedrock preflight token counting and concurrency-safe budget reservations
- configuration-driven mock, local, and cloud provider registration
- AWS disabled by default with fail-closed budget configuration
- security-hardened raw Kubernetes manifests for local `kind` use
- Helm deployment with optional development Redis and external-secret support
- live CI deployment and inference smoke tests on an ephemeral `kind` cluster
- Terraform for Cloud Run, Artifact Registry, least-privilege runtime identity, and budget alerts
- Cloud Run scale-to-zero with an explicit maximum-instance ceiling
- repeatable HTTP load comparison across four routing policies
- p50, p95, p99, throughput, cost, provider-distribution, and fallback reports
- repeated provider error, timeout, circuit, recovery, and total-outage scenarios
- downloadable machine-readable evaluation artifacts from GitHub Actions

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

## Local Ollama provider

Install Ollama, pull a model that fits the machine, and start its local service:

~~~bash
ollama pull qwen2.5:0.5b
OLLAMA_ENABLED=true uvicorn control_plane.main:app --reload --port 8080
~~~

The public gateway model name is `ollama-local`; `OLLAMA_MODEL` identifies the actual model loaded by Ollama. The adapter sends the complete conversation to Ollama's native chat endpoint and reports its real prompt and completion token counts. It has a configured estimated cost of zero.

## Amazon Bedrock provider

Bedrock remains disabled unless every safety setting is supplied. The adapter uses Bedrock `CountTokens` before inference, reserves the maximum request cost atomically, invokes the unified Converse API, and settles the reservation against returned usage.

~~~bash
AWS_BEDROCK_ENABLED=true \
AWS_REGION=us-east-1 \
AWS_BEDROCK_MODEL_ID='<approved-model-or-inference-profile-id>' \
AWS_BEDROCK_INPUT_COST_PER_MILLION_TOKENS_USD='<current-price>' \
AWS_BEDROCK_OUTPUT_COST_PER_MILLION_TOKENS_USD='<current-price>' \
AWS_SESSION_BUDGET_USD=5 \
uvicorn control_plane.main:app --port 8080
~~~

Use the public model alias `bedrock-primary`. Credentials are resolved by the standard AWS SDK credential chain and must never be committed. The session guard is a process-level experimental control, not a replacement for AWS Budgets, account quotas, or billing alerts. Prices are explicit configuration because they vary by model and region and must be verified immediately before a paid experiment.

## Kubernetes and Helm

The raw development manifests are under `deploy/kubernetes/base`. They run two non-root gateway replicas with health probes, resource limits, a read-only filesystem, no service-account token mount, and mock providers only.

The reusable chart is under `deploy/helm/control-plane`. Its default configuration does not enable Redis, Ollama, or Bedrock. For a completely local disposable cluster with Redis:

~~~bash
kind create cluster --name control-plane
docker build -t adaptive-ai-inference-control-plane:local .
kind load docker-image adaptive-ai-inference-control-plane:local --name control-plane
helm upgrade --install demo deploy/helm/control-plane \
  --namespace inference-system \
  --create-namespace \
  --set image.pullPolicy=Never \
  --set redis.enabled=true
kubectl -n inference-system port-forward service/demo-control-plane 8080:80
~~~

The bundled Redis workload is for local and CI fault testing, not production persistence. Production deployments should reference a managed Redis URL through an existing Kubernetes Secret.

## Cloud Run Terraform

`infra/terraform/cloud-run` defines the free-first public gateway path. It creates Artifact Registry, a dedicated runtime identity, Cloud Run with scale-to-zero and a maximum of two instances, optional Secret Manager access, and optional $5 budget-alert thresholds.

CI runs `terraform init` and `terraform validate`, but never runs `terraform apply`. A billing budget sends alerts and does not hard-stop spending. See the directory README for the explicit plan, apply, and destroy workflow.

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `MOCK_PROVIDERS_ENABLED` | `true` | Keeps deterministic providers available for free tests |
| `OLLAMA_ENABLED` | `false` | Registers the real local Ollama provider |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama HTTP service |
| `OLLAMA_MODEL` | `qwen2.5:0.5b` | Locally installed Ollama model |
| `OLLAMA_MODEL_ALIAS` | `ollama-local` | Stable gateway-facing model name |
| `AWS_BEDROCK_ENABLED` | `false` | Registers the real Bedrock provider |
| `AWS_BEDROCK_MODEL_ID` | empty | Approved Bedrock model or inference profile ID |
| `AWS_BEDROCK_MODEL_ALIAS` | `bedrock-primary` | Stable gateway-facing model name |
| `AWS_BEDROCK_INPUT_COST_PER_MILLION_TOKENS_USD` | `0` | Explicit current input price; must be positive when enabled |
| `AWS_BEDROCK_OUTPUT_COST_PER_MILLION_TOKENS_USD` | `0` | Explicit current output price; must be positive when enabled |
| `AWS_SESSION_BUDGET_USD` | `0` | Fail-closed per-process experimental spending ceiling |
| `CACHE_ENABLED` | `true` | Enables exact-response caching |
| `REDIS_URL` | empty | Uses Redis when set; otherwise uses memory |
| `CACHE_TTL_SECONDS` | `300` | Exact-response cache lifetime |
| `IDEMPOTENCY_TTL_SECONDS` | `86400` | Retry record lifetime |
| `OTEL_SERVICE_NAME` | `adaptive-ai-inference-control-plane` | Trace service identity |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | empty | Optional OTLP/HTTP trace destination |
| `TELEMETRY_RECENT_EVENTS_LIMIT` | `100` | Maximum in-memory dashboard events |
| `PROVIDER_RATE_PER_SECOND` | `100` | Per-provider token-bucket refill rate |
| `PROVIDER_BURST_CAPACITY` | `100` | Per-provider token-bucket burst ceiling |
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
The infrastructure job additionally lints the Helm chart, validates Terraform, creates an ephemeral `kind` cluster, deploys the chart, waits for both workloads, and sends a real inference request through the Kubernetes Service.

The evaluation job runs 400 HTTP requests across all four routing profiles plus 12 provider-fault scenarios. See [`docs/evaluation.md`](docs/evaluation.md) for the complete 12,000-request and 60-scenario evidence workflow.

## Evidence policy

Mock-provider prices, quality scores, latency, and failures are controlled simulation inputs. No production performance, cost-reduction, recovery-time, vLLM, Bedrock, Kubernetes, or cloud-provider claim will be published until repeated experiments retain machine-readable evidence.

## Roadmap

1. Safe service foundation — complete
2. OpenAI-compatible gateway and deterministic providers — complete
3. Adaptive constraint-aware routing — complete
4. Provider isolation, circuit breaking, admission control, and fallback — complete
5. Redis caching and retry idempotency — complete
6. Metrics, tracing, and observability dashboard — complete
7. Local and cloud model adapters — complete in code; paid cloud validation pending
8. Kubernetes, Helm, and Terraform — complete; cloud apply intentionally pending
9. Repeated benchmarks and fault injection — complete in code; full evidence run pending
10. Controlled cloud validation and v1.0 release

## License

MIT
