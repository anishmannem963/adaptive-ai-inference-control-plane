"""Safe environment-backed configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping


class ConfigurationError(ValueError):
    """Configuration is unsafe or invalid."""


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError("AWS_BEDROCK_ENABLED must be a boolean")


def parse_budget(value: str) -> Decimal:
    try:
        budget = Decimal(value)
    except InvalidOperation as exc:
        raise ConfigurationError("AWS_SESSION_BUDGET_USD must be a decimal") from exc
    if not budget.is_finite() or budget < 0:
        raise ConfigurationError("AWS_SESSION_BUDGET_USD must be finite and non-negative")
    return budget


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str = "development"
    aws_bedrock_enabled: bool = False
    aws_region: str = "us-east-1"
    aws_model_id: str = ""
    aws_session_budget_usd: Decimal = Decimal("0")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        source = os.environ if env is None else env
        settings = cls(
            environment=source.get("APP_ENV", "development"),
            aws_bedrock_enabled=parse_bool(source.get("AWS_BEDROCK_ENABLED", "false")),
            aws_region=source.get("AWS_REGION", "us-east-1"),
            aws_model_id=source.get("AWS_BEDROCK_MODEL_ID", ""),
            aws_session_budget_usd=parse_budget(source.get("AWS_SESSION_BUDGET_USD", "0")),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.aws_bedrock_enabled and self.aws_session_budget_usd <= 0:
            raise ConfigurationError("Bedrock requires a positive AWS_SESSION_BUDGET_USD")
        if self.aws_bedrock_enabled and not self.aws_model_id:
            raise ConfigurationError("Bedrock requires AWS_BEDROCK_MODEL_ID")
