# Adaptive AI Inference Control Plane

An evidence-driven platform for cost-, latency-, quality-, and health-aware routing across AI inference backends.

## Status

Iteration 1 adds an OpenAI-compatible chat boundary and three deterministic providers. Adaptive routing, production reliability, cloud adapters, and performance claims remain intentionally pending.

## Implemented

- typed FastAPI service and OpenAPI documentation
- OpenAI-compatible non-streaming chat request and response contracts
- explicit provider protocol and model registry
- economy, fast, and quality-oriented deterministic providers
- request ID propagation and provider attribution
- bounded provider deadline
- paid-provider fail-closed configuration
- CI checks for linting, formatting, typing, tests, and container builds

The mock providers expose controlled price, latency, and quality profiles. They enable reproducible routing and fault experiments; they are not real model inference.

## Quick start

~~~bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn control_plane.main:app --reload --port 8080
~~~

Or run:

~~~bash
docker compose up --build
~~~

List models:

~~~bash
curl http://localhost:8080/v1/models
~~~

Send a completion:

~~~bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: demo-1" \
  -d '{"model":"mock-fast","messages":[{"role":"user","content":"Explain quorum."}]}'
~~~

Additional endpoints:

- /health/live
- /health/ready
- /v1/system/status
- /docs

## Safety

The default mode is free: AWS Bedrock is disabled, its session budget is zero, and no credentials are required. Enabling Bedrock without an explicit model ID and positive budget prevents application startup.

## Planned modes

| Mode | Backends | Cost |
|---|---|---:|
| Deterministic | Mock providers | Free |
| Local | Ollama on Apple Silicon; vLLM on Linux GPU | Free when hardware is available |
| Cloud validation | AWS Bedrock and temporary remote vLLM | Explicitly budgeted and opt-in |

## Evidence policy

No cost reduction, performance, reliability, vLLM, Bedrock, or Kubernetes deployment claim will be published until repeated experiments produce retained machine-readable artifacts.

## Roadmap

1. Safe service foundation — complete
2. OpenAI-compatible gateway and deterministic providers — complete
3. Adaptive constraint-aware routing
4. Reliability, caching, and observability
5. Kubernetes, Helm, and Terraform
6. Repeated benchmarks and fault injection
7. Controlled cloud validation and v1.0 release

## License

MIT
