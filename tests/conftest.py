import pytest

from app.infrastructure.settings import get_settings


@pytest.fixture(autouse=True)
def isolate_local_auth_env(monkeypatch):
    """测试默认关闭认证，避免本机 .env 影响普通 API 用例。"""
    get_settings.cache_clear()
    monkeypatch.setenv("AUTH_ENABLED", "false")
    yield
    get_settings.cache_clear()
