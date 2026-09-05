"""Provider discovery and explicit model resolution."""

from __future__ import annotations

from control_plane.providers.base import InferenceProvider


class UnknownModelError(LookupError):
    """Requested model is not registered."""


class ProviderRegistry:
    def __init__(self, providers: tuple[InferenceProvider, ...]) -> None:
        self._providers = providers
        self._by_model = {
            model: provider for provider in providers for model in provider.descriptor.models
        }
        if len(self._by_model) != sum(len(provider.descriptor.models) for provider in providers):
            raise ValueError("provider model names must be unique")

    def resolve(self, model: str) -> InferenceProvider:
        try:
            return self._by_model[model]
        except KeyError as exc:
            raise UnknownModelError(model) from exc

    def list(self) -> tuple[InferenceProvider, ...]:
        return self._providers
