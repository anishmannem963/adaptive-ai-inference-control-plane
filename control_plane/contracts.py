"""Public API and internal provider contracts."""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Role = Literal["system", "user", "assistant"]
FinishReason = Literal["stop", "length"]
RoutingPolicy = Literal[
    "adaptive",
    "round_robin",
    "lowest_cost",
    "lowest_latency",
    "highest_quality",
    "single_provider",
]


class ChatMessage(BaseModel):
    role: Role
    content: str = Field(min_length=1, max_length=32_768)


class RoutingWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cost: float = Field(default=0.40, ge=0)
    latency: float = Field(default=0.35, ge=0)
    quality: float = Field(default=0.25, ge=0)

    @model_validator(mode="after")
    def require_positive_total(self) -> RoutingWeights:
        if self.cost + self.latency + self.quality <= 0:
            raise ValueError("at least one routing weight must be positive")
        return self


class RoutingOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy: RoutingPolicy = "adaptive"
    preferred_provider: str | None = None
    max_latency_ms: int | None = Field(default=None, ge=1)
    max_estimated_cost_usd: Decimal | None = Field(default=None, ge=0)
    min_quality: float | None = Field(default=None, ge=0, le=1)
    weights: RoutingWeights = Field(default_factory=RoutingWeights)

    @model_validator(mode="after")
    def validate_single_provider(self) -> RoutingOptions:
        if self.policy == "single_provider" and not self.preferred_provider:
            raise ValueError("single_provider requires preferred_provider")
        return self


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=128)
    messages: list[ChatMessage] = Field(min_length=1, max_length=128)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=256, ge=1, le=4096)
    stream: bool = False
    routing: RoutingOptions = Field(default_factory=RoutingOptions)

    @model_validator(mode="after")
    def require_user_message(self) -> ChatCompletionRequest:
        if not any(message.role == "user" for message in self.messages):
            raise ValueError("at least one user message is required")
        return self


class ResponseMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class ChatChoice(BaseModel):
    index: int = 0
    message: ResponseMessage
    finish_reason: FinishReason


class TokenUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class RoutingMetadata(BaseModel):
    provider: str
    policy: str
    decision_reason: str
    eligible_providers: list[str]
    attempted_providers: list[str]
    fallback_count: int
    request_id: str
    simulated: bool
    cache_hit: bool
    estimated_cost_usd: str
    latency_ms: float


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: list[ChatChoice]
    usage: TokenUsage
    routing: RoutingMetadata


class ProviderResult(BaseModel):
    text: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: FinishReason = "stop"
    estimated_cost_usd: str
