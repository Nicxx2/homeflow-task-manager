import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ai.providers.base import BaseAIProvider
from backend.app.ai.providers.ollama import OllamaProvider
from backend.app.ai.providers.rules_fallback import RulesFallbackProvider
from backend.app.ai.registry.provider_registry import ProviderRegistry
from backend.app.ai.schemas.classification import AIModelInfo, TaskClassificationResult
from backend.app.core.config import get_settings
from backend.app.models.ai_error_log import AIErrorLog
from backend.app.models.ai_model_registry import AIModelRegistry
from backend.app.models.ai_settings import AISettings
from backend.app.models.enums import EffortLevel

logger = logging.getLogger(__name__)


class AIOrchestratorService:
    def __init__(self, db: Session, provider_registry: ProviderRegistry | None = None):
        self.db = db
        if provider_registry is not None:
            self.registry = provider_registry
        else:
            settings = get_settings()
            self.registry = ProviderRegistry(
                providers=[
                    OllamaProvider(base_url=settings.ollama_base_url),
                    RulesFallbackProvider(),
                ]
            )

    def get_ai_settings(self) -> AISettings:
        current = self.db.get(AISettings, 1)
        if current:
            return current
        settings = get_settings()
        created = AISettings(
            id=1,
            ai_enabled=True,
            active_provider="ollama",
            active_model=settings.ollama_default_model,
            fallback_provider="rules",
            timeout_seconds=settings.ai_default_timeout_seconds,
        )
        self.db.add(created)
        self.db.commit()
        self.db.refresh(created)
        return created

    def classify_task(self, *, title: str, description: str) -> TaskClassificationResult:
        current = self.get_ai_settings()

        if not current.ai_enabled:
            return self._classify_with_provider(
                provider_name="rules",
                model="rules-default",
                title=title,
                description=description,
                timeout_seconds=current.timeout_seconds,
                fallback_used=True,
            )

        try:
            result = self._classify_with_provider(
                provider_name=current.active_provider,
                model=current.active_model,
                title=title,
                description=description,
                timeout_seconds=current.timeout_seconds,
                fallback_used=False,
            )
            return result
        except Exception as exc:
            self._record_error(
                provider_name=current.active_provider,
                model_identifier=current.active_model,
                error_type=type(exc).__name__,
                message=str(exc),
                context="primary-classification",
            )
            fallback_model = "rules-default"
            try:
                return self._classify_with_provider(
                    provider_name=current.fallback_provider,
                    model=fallback_model,
                    title=title,
                    description=description,
                    timeout_seconds=current.timeout_seconds,
                    fallback_used=True,
                )
            except Exception as fallback_exc:
                self._record_error(
                    provider_name=current.fallback_provider,
                    model_identifier=fallback_model,
                    error_type=type(fallback_exc).__name__,
                    message=str(fallback_exc),
                    context="fallback-classification",
                )
                raise

    def parse_assistant_intent(self, *, message: str, visible_members: list[str], today: str) -> dict | None:
        current = self.db.get(AISettings, 1)
        if not current or not current.ai_enabled or current.active_provider == "rules":
            return None

        prompt = (
            "You classify a Homeflow task assistant request. Return JSON only.\n"
            "Allowed intents: list_tasks, capacity, unsupported_action, help.\n"
            "Allowed task filters: effort low|medium|high|null, status active|pending|in_progress|completed|null, "
            "date YYYY-MM-DD|null, date_field due|assignment|either, assignee me|unassigned|one visible member name|null.\n"
            "Do not invent member names or dates. If the user asks to create, delete, edit, or move tasks, "
            "use unsupported_action because app-owned confirmation flows must handle writes.\n"
            "Schema: {\"intent\":\"list_tasks\",\"effort\":null,\"status\":\"active\",\"date\":null,"
            "\"date_field\":\"either\",\"assignee\":null,\"capacity_effort\":null,\"confidence\":0.0}\n"
            f"Today: {today}\n"
            f"Visible members: {', '.join(visible_members[:30])}\n"
            f"Message: {message[:500]}"
        )

        try:
            provider = self.registry.get(current.active_provider)
            return provider.generate_json(
                prompt=prompt,
                model=current.active_model,
                timeout_seconds=max(2, min(current.timeout_seconds, 8)),
                max_tokens=220,
            )
        except Exception as exc:
            self._record_error(
                provider_name=current.active_provider,
                model_identifier=current.active_model,
                error_type=type(exc).__name__,
                message=str(exc),
                context="assistant-intent",
            )
            return None

    def _classify_with_provider(
        self,
        *,
        provider_name: str,
        model: str,
        title: str,
        description: str,
        timeout_seconds: int,
        fallback_used: bool,
    ) -> TaskClassificationResult:
        provider = self.registry.get(provider_name)
        output = provider.classify_task(
            title=title,
            description=description,
            model=model,
            timeout_seconds=timeout_seconds,
        )
        return TaskClassificationResult(
            suggested_level=output.suggested_level,
            confidence=output.confidence,
            reason=output.reason,
            provider_used=provider.provider_name,
            model_used=model,
            fallback_used=fallback_used,
        )

    def refresh_model_registry(self) -> list[AIModelRegistry]:
        current = self.get_ai_settings()
        timeout_seconds = current.timeout_seconds
        now = datetime.now(timezone.utc)

        discovered: list[AIModelInfo] = []
        for name in self.registry.names():
            provider = self.registry.get(name)
            try:
                discovered.extend(provider.list_models(timeout_seconds=timeout_seconds))
            except Exception as exc:
                self._record_error(
                    provider_name=name,
                    model_identifier=None,
                    error_type=type(exc).__name__,
                    message=str(exc),
                    context="model-discovery",
                )

        for info in discovered:
            existing = self.db.scalar(
                select(AIModelRegistry).where(
                    AIModelRegistry.provider_name == info.provider_name,
                    AIModelRegistry.model_identifier == info.model_identifier,
                )
            )
            if existing:
                existing.display_name = info.display_name
                existing.available = info.available
                existing.enabled = info.enabled
                existing.health_status = info.health_status
                existing.last_checked_at = now
                existing.notes = info.notes
            else:
                self.db.add(
                    AIModelRegistry(
                        display_name=info.display_name,
                        provider_name=info.provider_name,
                        model_identifier=info.model_identifier,
                        available=info.available,
                        enabled=info.enabled,
                        health_status=info.health_status,
                        last_checked_at=now,
                        notes=info.notes,
                    )
                )

        self.db.commit()
        return list(
            self.db.scalars(
                select(AIModelRegistry).order_by(AIModelRegistry.provider_name.asc(), AIModelRegistry.display_name.asc())
            ).all()
        )

    def list_registry_models(self) -> list[AIModelRegistry]:
        return list(
            self.db.scalars(
                select(AIModelRegistry).order_by(AIModelRegistry.provider_name.asc(), AIModelRegistry.display_name.asc())
            ).all()
        )

    def test_current_provider(self, *, sample_title: str, sample_description: str) -> dict:
        current = self.get_ai_settings()
        # Provider test should be more tolerant on local CPU hosts.
        effective_timeout = max(current.timeout_seconds, 45)
        try:
            result = self._classify_with_provider(
                provider_name=current.active_provider,
                model=current.active_model,
                title=sample_title,
                description=sample_description,
                timeout_seconds=effective_timeout,
                fallback_used=False,
            )
            return {"ok": True, "result": result.model_dump()}
        except Exception as exc:
            self._record_error(
                provider_name=current.active_provider,
                model_identifier=current.active_model,
                error_type=type(exc).__name__,
                message=str(exc),
                context="provider-test",
            )
            return {"ok": False, "error": str(exc)}

    def provider_health(self) -> list[dict]:
        current = self.get_ai_settings()
        if not current.ai_enabled:
            return [
                {
                    "provider_name": "rules",
                    "ok": True,
                    "message": "AI is disabled. Rules fallback is active.",
                }
            ]
        rows: list[dict] = []
        effective_timeout = max(current.timeout_seconds, 20)
        for name in self.registry.names():
            provider = self.registry.get(name)
            model = current.active_model if name == current.active_provider else "rules-default"
            try:
                result = provider.health_check(model=model, timeout_seconds=effective_timeout)
                rows.append({"provider_name": name, "ok": bool(result.get("ok")), "message": result.get("message", "")})
            except Exception as exc:
                self._record_error(
                    provider_name=name,
                    model_identifier=model,
                    error_type=type(exc).__name__,
                    message=str(exc),
                    context="health-check",
                )
                rows.append({"provider_name": name, "ok": False, "message": str(exc)})
        return rows

    def update_settings(
        self,
        *,
        ai_enabled: bool,
        active_provider: str,
        active_model: str,
        fallback_provider: str,
        timeout_seconds: int,
    ) -> AISettings:
        current = self.get_ai_settings()
        if active_provider not in self.registry.names():
            raise ValueError("Unknown active provider.")
        if fallback_provider not in self.registry.names():
            raise ValueError("Unknown fallback provider.")
        if timeout_seconds <= 0:
            raise ValueError("Timeout must be positive.")
        if not active_model.strip():
            raise ValueError("Active model is required.")

        current.ai_enabled = ai_enabled
        current.active_provider = active_provider
        current.active_model = active_model.strip()
        current.fallback_provider = fallback_provider
        current.timeout_seconds = timeout_seconds
        self.db.add(current)
        self.db.commit()
        self.db.refresh(current)
        return current

    def recent_errors(self, limit: int = 15) -> list[AIErrorLog]:
        stmt = select(AIErrorLog).order_by(AIErrorLog.created_at.desc()).limit(limit)
        return list(self.db.scalars(stmt).all())

    def log_error(
        self,
        *,
        provider_name: str,
        model_identifier: str | None,
        error_type: str,
        message: str,
        context: str,
    ) -> None:
        self._record_error(
            provider_name=provider_name,
            model_identifier=model_identifier,
            error_type=error_type,
            message=message,
            context=context,
        )

    def _record_error(
        self,
        *,
        provider_name: str,
        model_identifier: str | None,
        error_type: str,
        message: str,
        context: str,
    ) -> None:
        logger.warning(
            "ai_error provider=%s model=%s type=%s context=%s message=%s",
            provider_name,
            model_identifier,
            error_type,
            context,
            message,
        )
        self.db.add(
            AIErrorLog(
                provider_name=provider_name,
                model_identifier=model_identifier,
                error_type=error_type,
                message=message[:3000],
                context=context,
            )
        )
        self.db.commit()
