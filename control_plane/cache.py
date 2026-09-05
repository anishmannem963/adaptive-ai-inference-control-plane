"""Exact response caching and retry-safe request deduplication."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Protocol

import redis.asyncio as redis

from control_plane.contracts import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ProviderResult,
)


class AsyncKeyValue(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl_seconds: int) -> None: ...


class MemoryKeyValue:
    def __init__(self) -> None:
        self._values: dict[str, tuple[float, str]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> str | None:
        async with self._lock:
            item = self._values.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at <= time.monotonic():
                del self._values[key]
                return None
            return value

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        async with self._lock:
            self._values[key] = (time.monotonic() + ttl_seconds, value)


class RedisKeyValue:
    def __init__(self, url: str) -> None:
        self._client = redis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> str | None:
        value = await self._client.get(key)
        return str(value) if value is not None else None

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        await self._client.set(key, value, ex=ttl_seconds)


@dataclass(slots=True)
class CacheStatistics:
    hits: int = 0
    misses: int = 0
    writes: int = 0
    backend_errors: int = 0
    idempotent_replays: int = 0
    idempotency_conflicts: int = 0


class ResilientKeyValue:
    """Fail-open wrapper: cache outages must not stop inference."""

    def __init__(self, backend: AsyncKeyValue, statistics: CacheStatistics) -> None:
        self._backend = backend
        self._statistics = statistics

    async def get(self, key: str) -> str | None:
        try:
            return await self._backend.get(key)
        except Exception:
            self._statistics.backend_errors += 1
            return None

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        try:
            await self._backend.set(key, value, ttl_seconds)
        except Exception:
            self._statistics.backend_errors += 1


class ExactResponseCache:
    def __init__(
        self,
        backend: AsyncKeyValue,
        ttl_seconds: int = 300,
        statistics: CacheStatistics | None = None,
    ) -> None:
        self.statistics = statistics or CacheStatistics()
        self._backend = ResilientKeyValue(backend, self.statistics)
        self._ttl_seconds = ttl_seconds

    def key(self, request: ChatCompletionRequest, provider: str) -> str:
        material = json.dumps(
            {
                "provider": provider,
                "messages": [message.model_dump() for message in request.messages],
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(material.encode()).hexdigest()
        return f"inference-cache:v1:{digest}"

    async def get(
        self,
        request: ChatCompletionRequest,
        provider: str,
    ) -> ProviderResult | None:
        value = await self._backend.get(self.key(request, provider))
        if value is None:
            self.statistics.misses += 1
            return None
        try:
            result = ProviderResult.model_validate_json(value)
        except ValueError:
            self.statistics.backend_errors += 1
            self.statistics.misses += 1
            return None
        self.statistics.hits += 1
        return result

    async def set(
        self,
        request: ChatCompletionRequest,
        provider: str,
        result: ProviderResult,
    ) -> None:
        await self._backend.set(
            self.key(request, provider),
            result.model_dump_json(),
            self._ttl_seconds,
        )
        self.statistics.writes += 1


class IdempotencyConflictError(RuntimeError):
    """A retry key was reused with a different request payload."""


class IdempotencyStore:
    def __init__(
        self,
        backend: AsyncKeyValue,
        ttl_seconds: int = 86_400,
        statistics: CacheStatistics | None = None,
    ) -> None:
        self.statistics = statistics or CacheStatistics()
        self._backend = ResilientKeyValue(backend, self.statistics)
        self._ttl_seconds = ttl_seconds

    def _key(self, client_id: str, idempotency_key: str) -> str:
        raw = f"{client_id}:{idempotency_key}".encode()
        return f"idempotency:v1:{hashlib.sha256(raw).hexdigest()}"

    def _fingerprint(self, request: ChatCompletionRequest) -> str:
        return hashlib.sha256(request.model_dump_json().encode()).hexdigest()

    async def replay(
        self,
        client_id: str,
        idempotency_key: str,
        request: ChatCompletionRequest,
    ) -> ChatCompletionResponse | None:
        value = await self._backend.get(self._key(client_id, idempotency_key))
        if value is None:
            return None
        record = json.loads(value)
        if record["fingerprint"] != self._fingerprint(request):
            self.statistics.idempotency_conflicts += 1
            raise IdempotencyConflictError("idempotency key reused with different request")
        self.statistics.idempotent_replays += 1
        return ChatCompletionResponse.model_validate(record["response"])

    async def store(
        self,
        client_id: str,
        idempotency_key: str,
        request: ChatCompletionRequest,
        response: ChatCompletionResponse,
    ) -> None:
        value = json.dumps(
            {
                "fingerprint": self._fingerprint(request),
                "response": response.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        await self._backend.set(
            self._key(client_id, idempotency_key),
            value,
            self._ttl_seconds,
        )
