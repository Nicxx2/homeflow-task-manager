from pydantic import BaseModel, Field, field_validator

from backend.app.models.enums import EffortLevel


class TaskClassificationResult(BaseModel):
    model_config = {"protected_namespaces": ()}

    suggested_level: EffortLevel
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=3, max_length=500)
    provider_used: str
    model_used: str
    fallback_used: bool = False


class ProviderTaskClassificationOutput(BaseModel):
    suggested_level: EffortLevel
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=3, max_length=500)


class AIModelInfo(BaseModel):
    model_config = {"protected_namespaces": ()}

    display_name: str
    provider_name: str
    model_identifier: str
    available: bool = True
    enabled: bool = True
    health_status: str = "unknown"
    notes: str | None = None

    @field_validator("provider_name")
    @classmethod
    def provider_name_lower(cls, value: str) -> str:
        return value.strip().lower()
