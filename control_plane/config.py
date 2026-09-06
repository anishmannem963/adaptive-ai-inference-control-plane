"""Safe environment-backed configuration."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse


class ConfigurationError(ValueError):
    """Configuration is unsafe or invalid."""


def parse_bool(value: str, setting: str = "AWS_BEDROCK_ENABLED") -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{setting} must be a boolean")


def parse_decimal(value: str, setting: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ConfigurationError(f"{setting} must be a decimal") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ConfigurationError(f"{setting} must be finite and non-negative")
    return parsed


def parse_score(value: str, setting: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigurationError(f"{setting} must be a number") from exc
    if not 0 <= parsed <= 1:
        raise ConfigurationError(f"{setting} must be between 0 and 1")
    return parsed


def parse_positive_int(value: str, setting: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{setting} must be an integer") from exc
    if parsed <= 0:
        raise ConfigurationError(f"{setting} must be positive")
    return parsed


def parse_positive_float(value: str, setting: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigurationError(f"{setting} must be a number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ConfigurationError(f"{setting} must be positive")
    return parsed


def parse_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str = "development"
    mock_providers_enabled: bool = True
    ollama_enabled: bool = False
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:0.5b"
    ollama_model_alias: str = "ollama-local"
    ollama_nominal_latency_ms: int = 800
    ollama_quality_score: float = 0.75
    aws_bedrock_enabled: bool = False
    aws_region: str = "us-east-1"
    aws_model_id: str = ""
    aws_model_alias: str = "bedrock-primary"
    aws_input_cost_per_million_tokens_usd: Decimal = Decimal("0")
    aws_output_cost_per_million_tokens_usd: Decimal = Decimal("0")
    aws_nominal_latency_ms: int = 1200
    aws_quality_score: float = 0.90
    aws_session_budget_usd: Decimal = Decimal("0")
    cache_enabled: bool = True
    redis_url: str = ""
    cache_ttl_seconds: int = 300
    idempotency_ttl_seconds: int = 86_400
    telemetry_service_name: str = "adaptive-ai-inference-control-plane"
    otel_exporter_otlp_endpoint: str = ""
    telemetry_recent_events_limit: int = 100
    provider_rate_per_second: float = 100.0
    provider_burst_capacity: int = 100
    cors_allowed_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://localhost:8888",
    )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        source = os.environ if env is None else env
        settings = cls(
            environment=source.get("APP_ENV", "development"),
            mock_providers_enabled=parse_bool(
                source.get("MOCK_PROVIDERS_ENABLED", "true"),
                "MOCK_PROVIDERS_ENABLED",
            ),
            ollama_enabled=parse_bool(
                source.get("OLLAMA_ENABLED", "false"),
                "OLLAMA_ENABLED",
            ),
            ollama_base_url=source.get("OLLAMA_BASE_URL", "http://localhost:11434"),
            ollama_model=source.get("OLLAMA_MODEL", "qwen2.5:0.5b"),
            ollama_model_alias=source.get("OLLAMA_MODEL_ALIAS", "ollama-local"),
            ollama_nominal_latency_ms=parse_positive_int(
                source.get("OLLAMA_NOMINAL_LATENCY_MS", "800"),
                "OLLAMA_NOMINAL_LATENCY_MS",
            ),
            ollama_quality_score=parse_score(
                source.get("OLLAMA_QUALITY_SCORE", "0.75"),
                "OLLAMA_QUALITY_SCORE",
            ),
            aws_bedrock_enabled=parse_bool(
                source.get("AWS_BEDROCK_ENABLED", "false"),
                "AWS_BEDROCK_ENABLED",
            ),
            aws_region=source.get("AWS_REGION", "us-east-1"),
            aws_model_id=source.get("AWS_BEDROCK_MODEL_ID", ""),
            aws_model_alias=source.get("AWS_BEDROCK_MODEL_ALIAS", "bedrock-primary"),
            aws_input_cost_per_million_tokens_usd=parse_decimal(
                source.get("AWS_BEDROCK_INPUT_COST_PER_MILLION_TOKENS_USD", "0"),
                "AWS_BEDROCK_INPUT_COST_PER_MILLION_TOKENS_USD",
            ),
            aws_output_cost_per_million_tokens_usd=parse_decimal(
                source.get("AWS_BEDROCK_OUTPUT_COST_PER_MILLION_TOKENS_USD", "0"),
                "AWS_BEDROCK_OUTPUT_COST_PER_MILLION_TOKENS_USD",
            ),
            aws_nominal_latency_ms=parse_positive_int(
                source.get("AWS_BEDROCK_NOMINAL_LATENCY_MS", "1200"),
                "AWS_BEDROCK_NOMINAL_LATENCY_MS",
            ),
            aws_quality_score=parse_score(
                source.get("AWS_BEDROCK_QUALITY_SCORE", "0.90"),
                "AWS_BEDROCK_QUALITY_SCORE",
            ),
            aws_session_budget_usd=parse_decimal(
                source.get("AWS_SESSION_BUDGET_USD", "0"),
                "AWS_SESSION_BUDGET_USD",
            ),
            cache_enabled=parse_bool(source.get("CACHE_ENABLED", "true"), "CACHE_ENABLED"),
            redis_url=source.get("REDIS_URL", ""),
            cache_ttl_seconds=parse_positive_int(
                source.get("CACHE_TTL_SECONDS", "300"),
                "CACHE_TTL_SECONDS",
            ),
            idempotency_ttl_seconds=parse_positive_int(
                source.get("IDEMPOTENCY_TTL_SECONDS", "86400"),
                "IDEMPOTENCY_TTL_SECONDS",
            ),
            telemetry_service_name=source.get(
                "OTEL_SERVICE_NAME",
                "adaptive-ai-inference-control-plane",
            ),
            otel_exporter_otlp_endpoint=source.get("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
            telemetry_recent_events_limit=parse_positive_int(
                source.get("TELEMETRY_RECENT_EVENTS_LIMIT", "100"),
                "TELEMETRY_RECENT_EVENTS_LIMIT",
            ),
            provider_rate_per_second=parse_positive_float(
                source.get("PROVIDER_RATE_PER_SECOND", "100"),
                "PROVIDER_RATE_PER_SECOND",
            ),
            provider_burst_capacity=parse_positive_int(
                source.get("PROVIDER_BURST_CAPACITY", "100"),
                "PROVIDER_BURST_CAPACITY",
            ),
            cors_allowed_origins=parse_csv(
                source.get(
                    "CORS_ALLOWED_ORIGINS",
                    "http://localhost:5173,http://localhost:8888",
                )
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if (
            not self.mock_providers_enabled
            and not self.ollama_enabled
            and not self.aws_bedrock_enabled
        ):
            raise ConfigurationError("at least one inference provider must be enabled")
        if self.ollama_enabled:
            parsed_url = urlparse(self.ollama_base_url)
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                raise ConfigurationError("OLLAMA_BASE_URL must be an HTTP(S) URL")
            if not self.ollama_model.strip() or not self.ollama_model_alias.strip():
                raise ConfigurationError("Ollama requires model and alias values")
        if self.aws_bedrock_enabled and self.aws_session_budget_usd <= 0:
            raise ConfigurationError("Bedrock requires a positive AWS_SESSION_BUDGET_USD")
        if self.aws_bedrock_enabled and not self.aws_model_id:
            raise ConfigurationError("Bedrock requires AWS_BEDROCK_MODEL_ID")
        if self.aws_bedrock_enabled and not self.aws_model_alias.strip():
            raise ConfigurationError("Bedrock requires AWS_BEDROCK_MODEL_ALIAS")
        if self.aws_bedrock_enabled and (
            self.aws_input_cost_per_million_tokens_usd <= 0
            or self.aws_output_cost_per_million_tokens_usd <= 0
        ):
            raise ConfigurationError("Bedrock requires positive configured token prices")
        if not self.telemetry_service_name.strip():
            raise ConfigurationError("OTEL_SERVICE_NAME must not be empty")
