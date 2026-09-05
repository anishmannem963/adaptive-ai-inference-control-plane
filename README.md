# Adaptive AI Inference Control Plane

An evidence-driven platform for cost-, latency-, quality-, and health-aware routing across AI inference backends.

## Status

Iteration 3 adds health-aware execution, provider isolation, bounded failover, and recovery-state tracking. Aggregate reliability and recovery-time claims remain pending until the repeated fault matrix is complete.

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
- provider health, failure, success, circuit, and latency inspection
- AWS disabled by default with fail-closed budget configuration

## Reliability behavior

Auto-routed requests can try each eligible provider at most once. A failed provider is excluded before the request is rerouted. Explicit model requests never fall back to a different model.

Open circuits reject traffic until their recovery interval passes. Exactly one request is then permitted as a half-open recovery probe. Success closes the circuit; failure reopens it.

Inspect runtime state:

~~~bash
curl http://localhost:8080/v1/providers/health
~~~

A completion response identifies every attempted provider and the fallback count.

## Run locally

~~~bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn control_plane.main:app --reload --port 8080
~~~

Or:

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

## Evidence policy

Mock-provider prices, quality scores, latency, and failures are controlled simulation inputs. No production performance, cost-reduction, recovery-time, vLLM, Bedrock, or Kubernetes claim will be published until repeated experiments retain machine-readable evidence.

## Roadmap

1. Safe service foundation — complete
2. OpenAI-compatible gateway and deterministic providers — complete
3. Adaptive constraint-aware routing — complete
4. Provider isolation, circuit breaking, admission control, and fallback — complete
5. Caching and observability
6. Local and cloud model adapters
7. Kubernetes, Helm, and Terraform
8. Repeated benchmarks and fault injection
9. Controlled cloud validation and v1.0 release

## License

MIT
