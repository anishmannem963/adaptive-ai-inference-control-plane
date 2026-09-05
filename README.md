# Adaptive AI Inference Control Plane

An evidence-driven platform for cost-, latency-, quality-, and health-aware routing across AI inference backends.

## Status

Iteration 0 establishes the safe service foundation. No performance, cost reduction, reliability, vLLM, Bedrock, or Kubernetes deployment claims will be made until reproducible evidence exists.

## Safety

The default mode is free: AWS Bedrock is disabled, its session budget is zero, and no credentials are required. Enabling Bedrock without an explicit model ID and positive budget prevents application startup.

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

Endpoints:

- /health/live
- /health/ready
- /v1/system/status
- /docs

## Planned modes

| Mode | Backends | Cost |
|---|---|---:|
| Deterministic | Mock providers | Free |
| Local | Ollama on Apple Silicon; vLLM on Linux GPU | Free when hardware is available |
| Cloud validation | AWS Bedrock and temporary remote vLLM | Explicitly budgeted and opt-in |

## Roadmap

1. Safe service foundation
2. OpenAI-compatible gateway and deterministic providers
3. Adaptive constraint-aware routing
4. Reliability, caching, and observability
5. Kubernetes, Helm, and Terraform
6. Repeated benchmarks and fault injection
7. Controlled cloud validation and v1.0 release

## License

MIT
