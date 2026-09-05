# Adaptive AI Inference Control Plane

An evidence-driven platform for cost-, latency-, quality-, and health-aware routing across AI inference backends.

## Status

Iteration 2 implements constraint-aware adaptive routing and reproducible comparison policies over three deterministic providers. Production health signals, resilience, real model adapters, and performance claims remain pending.

## Implemented

- typed FastAPI service with an OpenAI-compatible chat endpoint
- provider protocol, registry, and three deterministic provider profiles
- direct, single-provider, round-robin, lowest-cost, lowest-latency, highest-quality, and adaptive routing
- hard per-request cost, latency, and minimum-quality constraints
- normalized weighted adaptive scoring
- concurrency-safe round-robin state
- human-readable routing reasons and eligible-provider disclosure
- request IDs, deadlines, token usage, simulated status, latency, and cost metadata
- paid-provider fail-closed configuration
- CI for linting, formatting, strict typing, tests, and container builds

The deterministic providers make routing decisions reproducible without cloud charges. Their configured cost, latency, and quality values are simulation inputs, not real-provider measurements.

## Quick start

~~~bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn control_plane.main:app --reload --port 8080
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
      "min_quality": 0.75,
      "weights": {"cost": 0.4, "latency": 0.35, "quality": 0.25}
    }
  }'
~~~

Supported policies:

| Policy | Selection rule |
|---|---|
| direct | Explicit model name |
| single_provider | Required named provider |
| round_robin | Next eligible provider |
| lowest_cost | Minimum estimated request cost |
| lowest_latency | Minimum nominal latency |
| highest_quality | Maximum configured quality score |
| adaptive | Minimum normalized weighted cost-latency-quality score |

Hard constraints are never silently relaxed. If no provider qualifies, the gateway returns HTTP 422.

## Safety and evidence policy

AWS Bedrock remains disabled by default with a zero budget. No cost reduction, performance, reliability, vLLM, Bedrock, or Kubernetes claim will be published until repeated experiments produce retained machine-readable artifacts.

## Roadmap

1. Safe service foundation — complete
2. OpenAI-compatible gateway and deterministic providers — complete
3. Adaptive constraint-aware routing — complete
4. Reliability, caching, and observability
5. Kubernetes, Helm, and Terraform
6. Repeated benchmarks and fault injection
7. Controlled cloud validation and v1.0 release

## License

MIT
