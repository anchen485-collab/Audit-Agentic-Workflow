from pathlib import Path

import pytest

from app.infrastructure.settings import Settings, ensure_storage_dirs


def test_settings_has_default_values():
    """配置没有 .env 时也应该有安全默认值。"""
    settings = Settings(_env_file=None)

    assert settings.app_env == "local"
    assert settings.audit_storage_dir == Path("storage")
    assert settings.llm_enabled is False
    assert settings.company_provider == "mock"
    assert settings.auth_enabled is False
    assert settings.auth_tokens == ""
    assert settings.audit_max_excel_sheets == 5
    assert settings.audit_max_excel_rows == 5000
    assert settings.audit_max_excel_columns == 50
    assert settings.evidence_concurrency == 5
    assert settings.classification_concurrency == 3
    assert settings.rule_concurrency == 8
    assert settings.lightweight_agent_concurrency == 8
    assert settings.rule_recall_default_top_k == 5
    assert settings.rule_recall_max_top_k == 8
    assert settings.rule_recall_exact_match_score_threshold == 7


def test_ensure_storage_dirs_creates_directories(tmp_path):
    """启动时应该能自动创建上传目录和输出目录。"""
    settings = Settings(AUDIT_STORAGE_DIR=tmp_path)

    ensure_storage_dirs(settings)

    assert settings.uploads_dir.exists()
    assert settings.outputs_dir.exists()


def test_settings_does_not_require_llm_config_when_llm_disabled():
    """LLM 关闭时，不应该强制要求 API Key 和模型名称。"""
    settings = Settings(
        LLM_ENABLED=False,
        LLM_API_KEY="",
        LLM_MODEL="",
        _env_file=None,
    )

    assert settings.llm_enabled is False


def test_settings_requires_api_key_when_llm_enabled():
    """LLM 开启时，缺少 API Key 应该尽早失败。"""
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        Settings(
            LLM_ENABLED=True,
            LLM_API_KEY="",
            LLM_MODEL="deepseek-chat",
            LLM_BASE_URL="https://api.deepseek.com",
            _env_file=None,
        )


def test_settings_requires_model_when_llm_enabled():
    """LLM 开启时，缺少模型名称应该尽早失败。"""
    with pytest.raises(ValueError, match="LLM_MODEL"):
        Settings(
            LLM_ENABLED=True,
            LLM_API_KEY="sk-test",
            LLM_MODEL="",
            LLM_BASE_URL="https://api.deepseek.com",
            _env_file=None,
        )


def test_settings_requires_valid_base_url_when_llm_enabled():
    """LLM 开启时，base_url 必须是合法 URL。"""
    with pytest.raises(ValueError, match="LLM_BASE_URL"):
        Settings(
            LLM_ENABLED=True,
            LLM_API_KEY="sk-test",
            LLM_MODEL="deepseek-chat",
            LLM_BASE_URL="not-a-url",
            _env_file=None,
        )


def test_settings_validates_rule_recall_range():
    """规则召回配置应该限制在安全范围内，避免 prompt 过长。"""
    with pytest.raises(ValueError, match="RULE_RECALL_DEFAULT_TOP_K"):
        Settings(RULE_RECALL_DEFAULT_TOP_K=0, _env_file=None)

    with pytest.raises(ValueError, match="RULE_RECALL_MAX_TOP_K"):
        Settings(RULE_RECALL_MAX_TOP_K=13, _env_file=None)

    with pytest.raises(ValueError, match="RULE_RECALL_EXACT_MATCH_SCORE_THRESHOLD"):
        Settings(RULE_RECALL_EXACT_MATCH_SCORE_THRESHOLD=0, _env_file=None)
