"""Free gateway checks and explicitly guarded paid-provider validation."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from decimal import Decimal

import httpx

from control_plane.evaluation.load import percentile


@dataclass(frozen=True, slots=True)
class CloudSample:
    request_number: int
    status_code: int
    latency_ms: float
    provider: str | None
    estimated_cost_usd: str


def summarize_cloud_samples(
    *,
    kind: str,
    samples: list[CloudSample],
) -> dict[str, object]:
    successes = [sample for sample in samples if sample.status_code == 200]
    latencies = [sample.latency_ms for sample in successes]
    total_cost = sum(
        (Decimal(sample.estimated_cost_usd) for sample in successes),
        start=Decimal(0),
    )
    return {
        "schema_version": 1,
        "kind": kind,
        "summary": {
            "requests": len(samples),
            "successful_requests": len(successes),
            "failed_requests": len(samples) - len(successes),
            "success_rate": round(len(successes) / len(samples), 6) if samples else 0.0,
            "latency_ms": {
                "p50": round(percentile(latencies, 0.50), 3),
                "p95": round(percentile(latencies, 0.95), 3),
                "p99": round(percentile(latencies, 0.99), 3),
                "max": round(max(latencies), 3) if latencies else 0.0,
            },
            "total_estimated_cost_usd": format(total_cost, "f"),
        },
        "samples": [asdict(sample) for sample in samples],
    }


async def validate_free_gateway(
    client: httpx.AsyncClient,
    requests: int = 25,
    *,
    expected_cache_backend: str | None = None,
    allowed_origin: str | None = None,
) -> dict[str, object]:
    """Validate a deployment without permitting a real or paid provider."""
    health = await client.get("/health/ready")
    health.raise_for_status()

    status_response = await client.get("/v1/system/status")
    status_response.raise_for_status()
    status = status_response.json()
    if not status.get("mock_providers_enabled"):
        raise RuntimeError("free validation requires mock providers")
    if status.get("ollama_enabled") or status.get("aws_bedrock_enabled"):
        raise RuntimeError("free validation forbids Ollama and AWS Bedrock")
    if Decimal(status.get("aws_session_budget_usd", "0")) != 0:
        raise RuntimeError("free validation requires a zero Bedrock session budget")

    models_response = await client.get("/v1/models")
    models_response.raise_for_status()
    models = models_response.json().get("data", [])
    if not models or any(not model.get("simulated") for model in models):
        raise RuntimeError("free validation requires every registered model to be simulated")

    deployment_checks: dict[str, object] = {
        "ready": True,
        "mock_providers_enabled": True,
        "ollama_enabled": False,
        "aws_bedrock_enabled": False,
        "aws_session_budget_usd": "0",
        "all_models_simulated": True,
    }

    if expected_cache_backend is not None:
        cache_response = await client.get("/v1/cache/status")
        cache_response.raise_for_status()
        actual_backend = cache_response.json().get("backend")
        if actual_backend != expected_cache_backend:
            raise RuntimeError(
                f"expected {expected_cache_backend} cache backend, received {actual_backend}"
            )
        deployment_checks["cache_backend"] = actual_backend

    if allowed_origin is not None:
        cors_response = await client.options(
            "/v1/chat/completions",
            headers={
                "Origin": allowed_origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-request-id",
            },
        )
        cors_response.raise_for_status()
        actual_origin = cors_response.headers.get("access-control-allow-origin")
        if actual_origin != allowed_origin:
            raise RuntimeError(f"CORS does not allow the expected origin: {allowed_origin}")
        deployment_checks["allowed_origin"] = actual_origin

    samples: list[CloudSample] = []
    for request_number in range(1, requests + 1):
        started = time.perf_counter()
        response = await client.post(
            "/v1/chat/completions",
            headers={"X-Request-ID": f"cloud-free-{request_number}"},
            json={
                "model": "mock-fast",
                "messages": [
                    {"role": "user", "content": f"free cloud validation {request_number}"}
                ],
                "max_tokens": 16,
            },
        )
        body = response.json()
        routing = body.get("routing", {})
        samples.append(
            CloudSample(
                request_number=request_number,
                status_code=response.status_code,
                latency_ms=(time.perf_counter() - started) * 1000,
                provider=routing.get("provider"),
                estimated_cost_usd=routing.get("estimated_cost_usd", "0"),
            )
        )

    report = summarize_cloud_samples(kind="free-cloud-gateway-validation", samples=samples)
    report["deployment_checks"] = deployment_checks
    return report


async def validate_bedrock(
    client: httpx.AsyncClient,
    *,
    requests: int,
    maximum_total_estimated_cost_usd: Decimal,
) -> dict[str, object]:
    """Run a sequential, explicitly bounded Bedrock experiment through the gateway."""
    models = await client.get("/v1/models")
    models.raise_for_status()
    bedrock = next(
        (model for model in models.json()["data"] if model["id"] == "bedrock-primary"),
        None,
    )
    if bedrock is None or bedrock["simulated"]:
        raise RuntimeError("bedrock-primary must be registered as a real provider")

    samples: list[CloudSample] = []
    spent = Decimal(0)
    for request_number in range(1, requests + 1):
        if spent >= maximum_total_estimated_cost_usd:
            break
        started = time.perf_counter()
        response = await client.post(
            "/v1/chat/completions",
            headers={"X-Request-ID": f"bedrock-validation-{request_number}"},
            json={
                "model": "bedrock-primary",
                "messages": [
                    {
                        "role": "user",
                        "content": "Reply with exactly two words: validation passed",
                    }
                ],
                "temperature": 0,
                "max_tokens": 16,
            },
        )
        body = response.json()
        routing = body.get("routing", {})
        estimated_cost = Decimal(routing.get("estimated_cost_usd", "0"))
        spent += estimated_cost
        samples.append(
            CloudSample(
                request_number=request_number,
                status_code=response.status_code,
                latency_ms=(time.perf_counter() - started) * 1000,
                provider=routing.get("provider"),
                estimated_cost_usd=format(estimated_cost, "f"),
            )
        )

    report = summarize_cloud_samples(kind="minimal-paid-bedrock-validation", samples=samples)
    report["guardrails"] = {
        "requested_requests": requests,
        "client_estimated_cost_ceiling_usd": format(
            maximum_total_estimated_cost_usd,
            "f",
        ),
        "gateway_session_budget_required": True,
        "sequential_requests": True,
    }
    return report
