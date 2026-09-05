from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from control_plane.config import ConfigurationError, Settings
from control_plane.main import create_app


def test_cloud_is_disabled_by_default() -> None:
    settings = Settings.from_env({})
    assert settings.aws_bedrock_enabled is False
    assert settings.aws_session_budget_usd == Decimal("0")


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
            }
        )


def test_health_and_status() -> None:
    client = TestClient(create_app(Settings()))
    assert client.get("/health/live").json() == {"status": "alive", "version": "0.1.0"}
    assert client.get("/health/ready").status_code == 200
    assert client.get("/v1/system/status").json()["aws_bedrock_enabled"] is False
