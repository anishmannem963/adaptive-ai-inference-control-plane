# Changelog

All notable changes are documented here. The project follows Semantic Versioning after its
first public release.

## Unreleased

### Added

- Zero-cost Render Blueprint for the FastAPI gateway and volatile Key Value cache.
- Completely free hosted-demo runbook for the existing Netlify dashboard.
- Deployment tests that prevent paid-provider activation or non-free Render plans.
- Guarded free Cloud Run and minimal-paid AWS Bedrock validation clients.
- Permanent provenance summary for the Iteration 9 hosted evaluation.
- Release-candidate documentation and contribution guidance.

### Changed

- The production container now honors a hosting platform's assigned `PORT` while retaining
  port 8080 as its local default.

## 0.1.0 - Development baseline

- OpenAI-compatible FastAPI inference gateway.
- Constraint-aware adaptive and baseline routing policies.
- Deadlines, rate limiting, bulkheads, circuit breaking, and bounded fallback.
- Redis response caching and idempotent request replay.
- Prometheus metrics, OpenTelemetry tracing, and Netlify dashboard.
- Deterministic mock, local Ollama, and guarded AWS Bedrock adapters.
- Docker, Kubernetes, Helm, and plan-only Cloud Run Terraform.
- Reproducible HTTP load and controlled provider-fault matrices.

Version `1.0.0` remains intentionally unreleased until controlled cloud validation is complete.
