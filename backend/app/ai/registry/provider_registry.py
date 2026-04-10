from backend.app.ai.providers.base import BaseAIProvider


class ProviderRegistry:
    def __init__(self, providers: list[BaseAIProvider]):
        self._providers = {item.provider_name: item for item in providers}

    def get(self, provider_name: str) -> BaseAIProvider:
        normalized = provider_name.strip().lower()
        provider = self._providers.get(normalized)
        if not provider:
            raise ValueError(f"Unknown AI provider '{provider_name}'.")
        return provider

    def names(self) -> list[str]:
        return sorted(self._providers.keys())
