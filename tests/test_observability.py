from fastapi.testclient import TestClient

from control_plane.config import Settings
from control_plane.main import create_app


def completion_payload() -> dict[str, object]:
    return {
        "model": "mock-fast",
        "messages": [{"role": "user", "content": "show telemetry"}],
        "temperature": 0,
        "max_tokens": 32,
    }


def test_inference_emits_trace_metrics_and_summary_event() -> None:
    client = TestClient(create_app(Settings()))

    first = client.post(
        "/v1/chat/completions",
        headers={"X-Request-ID": "observable-request"},
        json=completion_payload(),
    )
    second = client.post("/v1/chat/completions", json=completion_payload())

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(first.headers["X-Trace-ID"]) == 32
    assert int(first.headers["X-Trace-ID"], 16) > 0
    assert first.headers["X-Cache"] == "MISS"
    assert second.headers["X-Cache"] == "HIT"

    summary = client.get("/v1/telemetry/summary").json()
    assert summary["completed_requests"] == 2
    assert summary["cache_hits"] == 1
    assert summary["cache_replays"] == 0
    assert summary["providers"]["mock-fast"]["calls"] == 1
    assert summary["providers"]["mock-fast"]["successes"] == 1
    assert summary["recent_events"][0]["cache_status"] == "HIT"
    assert summary["recent_events"][1]["request_id"] == "observable-request"

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain")
    assert "control_plane_http_requests_total" in metrics.text
    assert "control_plane_inference_requests_total" in metrics.text
    assert 'provider="mock-fast"' in metrics.text
    assert 'cache_status="HIT"' in metrics.text
    assert "control_plane_provider_calls_total" in metrics.text


def test_idempotent_replay_is_visible_in_telemetry() -> None:
    client = TestClient(create_app(Settings()))
    headers = {
        "X-Client-ID": "telemetry-test",
        "X-Idempotency-Key": "request-1",
    }

    first = client.post("/v1/chat/completions", headers=headers, json=completion_payload())
    replay = client.post("/v1/chat/completions", headers=headers, json=completion_payload())

    assert first.status_code == 200
    assert replay.status_code == 200
    summary = client.get("/v1/telemetry/summary").json()
    assert summary["completed_requests"] == 2
    assert summary["cache_replays"] == 1
    assert summary["recent_events"][0]["cache_status"] == "REPLAY"


def test_dashboard_origin_is_allowed_in_local_configuration() -> None:
    client = TestClient(create_app(Settings()))

    response = client.options(
        "/v1/telemetry/summary",
        headers={
            "Origin": "http://localhost:8888",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8888"


def test_telemetry_configuration_is_environment_backed() -> None:
    settings = Settings.from_env(
        {
            "OTEL_SERVICE_NAME": "test-control-plane",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318/v1/traces",
            "TELEMETRY_RECENT_EVENTS_LIMIT": "25",
            "CORS_ALLOWED_ORIGINS": "https://dashboard.example, http://localhost:8888",
        }
    )

    assert settings.telemetry_service_name == "test-control-plane"
    assert settings.otel_exporter_otlp_endpoint == "http://collector:4318/v1/traces"
    assert settings.telemetry_recent_events_limit == 25
    assert settings.cors_allowed_origins == (
        "https://dashboard.example",
        "http://localhost:8888",
    )
