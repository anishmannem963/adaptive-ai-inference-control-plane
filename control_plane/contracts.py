"""Public API and internal provider contracts."""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Role = Literal["system", "user", "assistant"]
FinishReason = Literal["stop", "length"]


class ChatMessage(BaseModel):
    role: Role
    content: str = Field(min_length=1, max_length=32_768)


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=128)
    messages: list[ChatMessage] = Field(min_length=1, max_length=128)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=256, ge=1, le=4096)
    stream: bool = False

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
    request_id: str
    simulated: bool
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
