from datetime import date, timedelta
from backend.app.ai.providers.base import BaseAIProvider
from backend.app.ai.registry.provider_registry import ProviderRegistry
from backend.app.ai.schemas.classification import AIModelInfo, ProviderTaskClassificationOutput
from backend.app.ai.services.orchestrator import AIOrchestratorService
from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.models.ai_settings import AISettings
from backend.app.models.enums import EffortLevel
from backend.app.models.task_effort_config import TaskEffortConfig
from backend.app.models.user import User
from backend.app.schemas.task import TaskCreate
from backend.app.services.admin_settings_service import AdminSettingsService
from backend.app.services.task_service import TaskService


class _FakePrimaryProvider(BaseAIProvider):
    provider_name = "primary"

    def __init__(self, should_fail: bool = False, invalid: bool = False):
        self.should_fail = should_fail
        self.invalid = invalid

    def classify_task(self, *, title: str, description: str, model: str, timeout_seconds: int):
        _ = (title, description, model, timeout_seconds)
        if self.should_fail:
            raise RuntimeError("primary failed")
        if self.invalid:
            return {"bad": "payload"}
        return ProviderTaskClassificationOutput(
            suggested_level=EffortLevel.HIGH,
            confidence=0.81,
            reason="Primary provider success.",
        )

    def list_models(self, *, timeout_seconds: int):
        _ = timeout_seconds
        return [AIModelInfo(display_name="Primary M", provider_name="primary", model_identifier="primary-model")]

    def health_check(self, *, model: str, timeout_seconds: int):
        _ = (model, timeout_seconds)
        return {"ok": True, "message": "ok"}


class _FakeFallbackProvider(BaseAIProvider):
    provider_name = "rules"

    def classify_task(self, *, title: str, description: str, model: str, timeout_seconds: int):
        _ = (title, description, model, timeout_seconds)
        return ProviderTaskClassificationOutput(
            suggested_level=EffortLevel.MEDIUM,
            confidence=0.64,
            reason="Fallback provider used.",
        )

    def list_models(self, *, timeout_seconds: int):
        _ = timeout_seconds
        return [AIModelInfo(display_name="Rules", provider_name="rules", model_identifier="rules-default")]

    def health_check(self, *, model: str, timeout_seconds: int):
        _ = (model, timeout_seconds)
        return {"ok": True, "message": "ok"}


def setup_module():
    Base.metadata.create_all(bind=engine)


def _seed_settings(db, active_provider="primary", active_model="primary-model", fallback_provider="rules"):
    row = db.get(AISettings, 1)
    if not row:
        row = AISettings(
            id=1,
            ai_enabled=True,
            active_provider=active_provider,
            active_model=active_model,
            fallback_provider=fallback_provider,
            timeout_seconds=5,
        )
        db.add(row)
    else:
        row.ai_enabled = True
        row.active_provider = active_provider
        row.active_model = active_model
        row.fallback_provider = fallback_provider
        row.timeout_seconds = 5
    db.commit()


def test_provider_abstraction_success_path():
    db = SessionLocal()
    try:
        _seed_settings(db)
        orchestrator = AIOrchestratorService(
            db,
            provider_registry=ProviderRegistry([_FakePrimaryProvider(), _FakeFallbackProvider()]),
        )
        result = orchestrator.classify_task(title="Refactor API", description="Complex migration and tests.")
        assert result.provider_used == "primary"
        assert result.fallback_used is False
        assert result.suggested_level == EffortLevel.HIGH
    finally:
        db.close()


def test_fallback_when_primary_fails():
    db = SessionLocal()
    try:
        _seed_settings(db)
        orchestrator = AIOrchestratorService(
            db,
            provider_registry=ProviderRegistry([_FakePrimaryProvider(should_fail=True), _FakeFallbackProvider()]),
        )
        result = orchestrator.classify_task(title="Task", description="desc")
        assert result.provider_used == "rules"
        assert result.fallback_used is True
    finally:
        db.close()


def test_invalid_payload_from_primary_triggers_fallback():
    db = SessionLocal()
    try:
        _seed_settings(db)
        orchestrator = AIOrchestratorService(
            db,
            provider_registry=ProviderRegistry([_FakePrimaryProvider(invalid=True), _FakeFallbackProvider()]),
        )
        result = orchestrator.classify_task(title="Task", description="desc")
        assert result.provider_used == "rules"
        assert result.fallback_used is True
    finally:
        db.close()


def test_task_create_still_requires_effort_level():
    db = SessionLocal()
    try:
        if not db.get(TaskEffortConfig, EffortLevel.MEDIUM):
            db.add(TaskEffortConfig(level=EffortLevel.MEDIUM, points_value=5))
            db.commit()
        user = db.query(User).filter(User.email == "phase4-user@example.com").first()
        if not user:
            user = User(email="phase4-user@example.com", full_name="Phase4 User", hashed_password="x")
            db.add(user)
            db.commit()
            db.refresh(user)

        payload = TaskCreate(
            title="A",
            description="B",
            due_date=date.today() + timedelta(days=1),
            effort_level=EffortLevel.MEDIUM,
            provider_used="rules",
            model_used="rules-default",
        )
        task = TaskService(db).create_unassigned_task(payload, user)
        assert task.effort_level == EffortLevel.MEDIUM
    finally:
        db.close()


def test_task_create_allows_empty_description_and_ai_can_use_title_only():
    db = SessionLocal()
    try:
        if not db.get(TaskEffortConfig, EffortLevel.MEDIUM):
            db.add(TaskEffortConfig(level=EffortLevel.MEDIUM, points_value=5))
            db.commit()
        user = db.query(User).filter(User.email == "phase4-empty-desc@example.com").first()
        if not user:
            user = User(email="phase4-empty-desc@example.com", full_name="Phase4 Empty Desc", hashed_password="x")
            db.add(user)
            db.commit()
            db.refresh(user)

        payload = TaskCreate(
            title="Quick task",
            description="",
            due_date=date.today() + timedelta(days=1),
            effort_level=EffortLevel.MEDIUM,
            provider_used="rules",
            model_used="rules-default",
        )
        task = TaskService(db).create_unassigned_task(payload, user)
        assert task.description == ""

        result = AIOrchestratorService(
            db,
            provider_registry=ProviderRegistry([_FakePrimaryProvider(), _FakeFallbackProvider()]),
        ).classify_task(title="Quick task", description="")
        assert result.suggested_level in {EffortLevel.HIGH, EffortLevel.MEDIUM}
    finally:
        db.close()


def test_admin_settings_update_logic():
    db = SessionLocal()
    try:
        service = AdminSettingsService(db)
        updated = service.update_ai_settings(
            ai_enabled=True,
            active_provider="rules",
            active_model="rules-default",
            fallback_provider="rules",
            timeout_seconds=7,
        )
        assert updated.active_provider == "rules"
        assert updated.active_model == "rules-default"
        assert updated.timeout_seconds == 7
    finally:
        db.close()


def test_model_discovery_registry_update():
    db = SessionLocal()
    try:
        _seed_settings(db)
        orchestrator = AIOrchestratorService(
            db,
            provider_registry=ProviderRegistry([_FakePrimaryProvider(), _FakeFallbackProvider()]),
        )
        models = orchestrator.refresh_model_registry()
        assert any(item.provider_name == "primary" for item in models)
        assert any(item.provider_name == "rules" for item in models)
    finally:
        db.close()


def test_invalid_json_handling_in_ollama_provider():
    from backend.app.ai.providers.ollama import OllamaProvider

    response = MockResponse(200, {"response": "not-json"})
    client = MockHttpClient([response, MockResponse(200, {"response": '{"suggested_level":"low","confidence":0.7,"reason":"ok"}'})])
    provider = OllamaProvider(base_url="http://x", client_factory=lambda timeout: client)
    result = provider.classify_task(title="A", description="B", model="m", timeout_seconds=3)
    assert result.suggested_level == EffortLevel.LOW


class MockResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self):
        return self._payload


class MockHttpClient:
    def __init__(self, responses):
        self._responses = responses

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, json):
        _ = (url, json)
        return self._responses.pop(0)

    def get(self, url):
        _ = url
        return MockResponse(200, {"models": []})
