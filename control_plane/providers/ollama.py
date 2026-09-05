"""Ollama chat adapter for zero-cost local model inference."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

import httpx

from control_plane.contracts import ChatCompletionRequest, ProviderResult
from control_plane.providers.base import ProviderDescriptor


@dataclass(slots=True)
class OllamaProvider:
    base_url: str
    model: str
    model_alias: str
    nominal_latency_ms: int
    quality_score: float
    client: httpx.AsyncClient | None = None

    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            name="ollama-local",
            models=(self.model_alias,),
            simulated=False,
            nominal_latency_ms=self.nominal_latency_ms,
            input_cost_per_million_tokens_usd="0",
            output_cost_per_million_tokens_usd="0",
            quality_score=self.quality_score,
        )

    async def complete(self, request: ChatCompletionRequest) -> ProviderResult:
        payload = {
            "model": self.model,
            "messages": [message.model_dump() for message in request.messages],
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }
        if self.client is None:
            async with httpx.AsyncClient(base_url=self.base_url) as client:
                response = await client.post("/api/chat", json=payload)
        else:
            response = await self.client.post("/api/chat", json=payload)
        response.raise_for_status()
        body = cast(dict[str, object], response.json())
        message = body.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ValueError("Ollama response did not contain assistant text")

        prompt_tokens = body.get("prompt_eval_count", 0)
        completion_tokens = body.get("eval_count", 0)
        if not isinstance(prompt_tokens, int) or prompt_tokens < 0:
            prompt_tokens = 0
        if not isinstance(completion_tokens, int) or completion_tokens < 0:
            completion_tokens = 0
        finish_reason: Literal["stop", "length"] = (
            "length" if body.get("done_reason") == "length" else "stop"
        )
        return ProviderResult(
            text=message["content"],
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=finish_reason,
            estimated_cost_usd="0",
        )
