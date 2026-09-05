from fastapi.testclient import TestClient

from control_plane.config import Settings
from control_plane.main import create_app


def client() -> TestClient:
    return TestClient(create_app(Settings()))


def test_lists_all_deterministic_models() -> None:
    response = client().get("/v1/models")

    assert response.status_code == 200
    models = response.json()["data"]
    assert {model["id"] for model in models} == {
        "mock-economy",
        "mock-fast",
        "mock-quality",
    }
    assert all(model["simulated"] for model in models)


def test_chat_completion_uses_requested_provider_and_request_id() -> None:
    response = client().post(
        "/v1/chat/completions",
        headers={"X-Request-ID": "test-request-42"},
        json={
            "model": "mock-fast",
            "messages": [{"role": "user", "content": "Explain quorum."}],
            "temperature": 0,
            "max_tokens": 64,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert response.headers["X-Request-ID"] == "test-request-42"
    assert body["id"] == "chatcmpl-test-request-42"
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert body["choices"][0]["message"]["content"] == "[mock-fast] Explain quorum."
    assert body["routing"]["provider"] == "mock-fast"
    assert body["routing"]["simulated"] is True
    assert body["usage"]["total_tokens"] > 0


def test_unknown_model_is_not_silently_substituted() -> None:
    response = client().post(
        "/v1/chat/completions",
        json={
            "model": "missing-model",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "unknown model: missing-model"


def test_request_requires_user_message() -> None:
    response = client().post(
        "/v1/chat/completions",
        json={
            "model": "mock-fast",
            "messages": [{"role": "system", "content": "Be concise."}],
        },
    )

    assert response.status_code == 422


def test_streaming_fails_explicitly_until_implemented() -> None:
    response = client().post(
        "/v1/chat/completions",
        json={
            "model": "mock-fast",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        },
    )

    assert response.status_code == 501
