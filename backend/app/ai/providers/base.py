from abc import ABC, abstractmethod

from backend.app.ai.schemas.classification import AIModelInfo, ProviderTaskClassificationOutput


class BaseAIProvider(ABC):
    provider_name: str

    @abstractmethod
    def classify_task(self, *, title: str, description: str, model: str, timeout_seconds: int) -> ProviderTaskClassificationOutput:
        raise NotImplementedError()

    @abstractmethod
    def list_models(self, *, timeout_seconds: int) -> list[AIModelInfo]:
        raise NotImplementedError()

    @abstractmethod
    def health_check(self, *, model: str, timeout_seconds: int) -> dict:
        raise NotImplementedError()
