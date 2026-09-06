from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from control_plane.config import ConfigurationError, Settings
from control_plane.main import create_app


def test_cloud_is_disabled_by_default() -> None:
    settings = Settings.from_env({})
    assert settings.ollama_enabled is False
    assert settings.aws_bedrock_enabled is False
    assert settings.aws_session_budget_usd == Decimal("0")
    assert settings.provider_rate_per_second == 100
    assert settings.provider_burst_capacity == 100


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "invalid"])
def test_provider_rate_must_be_positive_and_finite(value: str) -> None:
    with pytest.raises(ConfigurationError, match="PROVIDER_RATE_PER_SECOND"):
        Settings.from_env({"PROVIDER_RATE_PER_SECOND": value})


def test_bedrock_requires_budget() -> None:
    with pytest.raises(ConfigurationError, match="positive"):
        Settings.from_env(
            {
                "AWS_BEDROCK_ENABLED": "true",
                "AWS_BEDROCK_MODEL_ID": "model",
                "AWS_SESSION_BUDGET_USD": "0",
            }
        )


def test_bedrock_requires_model() -> None:
    with pytest.raises(ConfigurationError, match="MODEL_ID"):
        Settings.from_env(
            {
                "AWS_BEDROCK_ENABLED": "true",
                "AWS_SESSION_BUDGET_USD": "5",
                "AWS_BEDROCK_INPUT_COST_PER_MILLION_TOKENS_USD": "1",
                "AWS_BEDROCK_OUTPUT_COST_PER_MILLION_TOKENS_USD": "2",
            }
        )


def test_bedrock_requires_explicit_positive_prices() -> None:
    with pytest.raises(ConfigurationError, match="token prices"):
        Settings.from_env(
            {
                "AWS_BEDROCK_ENABLED": "true",
                "AWS_BEDROCK_MODEL_ID": "model",
                "AWS_SESSION_BUDGET_USD": "5",
            }
        )


def test_ollama_configuration_is_opt_in_and_validated() -> None:
    settings = Settings.from_env(
        {
            "OLLAMA_ENABLED": "true",
            "OLLAMA_BASE_URL": "http://localhost:11434",
            "OLLAMA_MODEL": "qwen2.5:0.5b",
        }
    )
    assert settings.ollama_enabled is True

    with pytest.raises(ConfigurationError, match="HTTP"):
        Settings.from_env(
            {
                "OLLAMA_ENABLED": "true",
                "OLLAMA_BASE_URL": "localhost:11434",
            }
        )


def test_health_and_status() -> None:
    client = TestClient(create_app(Settings()))
    assert client.get("/health/live").json() == {"status": "alive", "version": "0.1.0"}
    assert client.get("/health/ready").status_code == 200
    assert client.get("/v1/system/status").json()["aws_bedrock_enabled"] is False
