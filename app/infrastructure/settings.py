from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置，统一从环境变量和 .env 文件读取。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="local", alias="APP_ENV")
    audit_storage_dir: Path = Field(default=Path("storage"), alias="AUDIT_STORAGE_DIR")

    llm_enabled: bool = Field(default=False, alias="LLM_ENABLED")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_base_url: str = Field(default="https://api.openai.com/v1", alias="LLM_BASE_URL")
    llm_model: str = Field(default="", alias="LLM_MODEL")
    llm_health_check_enabled: bool = Field(default=True, alias="LLM_HEALTH_CHECK_ENABLED")

    company_provider: str = Field(default="mock", alias="COMPANY_PROVIDER")
    audit_log_level: str = Field(default="INFO", alias="AUDIT_LOG_LEVEL")
    auth_enabled: bool = Field(default=False, alias="AUTH_ENABLED")
    auth_tokens: str = Field(default="", alias="AUTH_TOKENS")
    audit_max_excel_sheets: int = Field(default=5, ge=1, le=20, alias="AUDIT_MAX_EXCEL_SHEETS")
    audit_max_excel_rows: int = Field(default=5000, ge=1, le=100000, alias="AUDIT_MAX_EXCEL_ROWS")
    audit_max_excel_columns: int = Field(default=50, ge=1, le=500, alias="AUDIT_MAX_EXCEL_COLUMNS")
    evidence_concurrency: int = Field(default=5, ge=1, le=20, alias="EVIDENCE_CONCURRENCY")
    classification_concurrency: int = Field(default=3, ge=1, le=10, alias="CLASSIFICATION_CONCURRENCY")
    rule_concurrency: int = Field(default=8, ge=1, le=20, alias="RULE_CONCURRENCY")
    lightweight_agent_concurrency: int = Field(default=8, ge=1, le=20, alias="LIGHTWEIGHT_AGENT_CONCURRENCY")
    case_retry_lock_timeout_seconds: int = Field(
        default=300,
        ge=30,
        le=3600,
        alias="CASE_RETRY_LOCK_TIMEOUT_SECONDS",
    )
    rule_recall_default_top_k: int = Field(default=5, ge=1, le=12, alias="RULE_RECALL_DEFAULT_TOP_K")
    rule_recall_max_top_k: int = Field(default=8, ge=1, le=12, alias="RULE_RECALL_MAX_TOP_K")
    rule_recall_exact_match_score_threshold: int = Field(
        default=7,
        ge=1,
        le=30,
        alias="RULE_RECALL_EXACT_MATCH_SCORE_THRESHOLD",
    )

    @model_validator(mode="after")
    def validate_llm_config(self):
        """启用真实 LLM 时，提前校验关键配置，避免批量审批跑到一半才失败。"""
        if not self.llm_enabled:
            return self

        if not self.llm_api_key.strip():
            raise ValueError("LLM_ENABLED=true 时必须配置 LLM_API_KEY。")

        if not self.llm_model.strip():
            raise ValueError("LLM_ENABLED=true 时必须配置 LLM_MODEL。")

        parsed_url = urlparse(self.llm_base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("LLM_BASE_URL 必须是合法的 http 或 https URL。")

        return self

    @model_validator(mode="after")
    def validate_rule_recall_config(self):
        """校验规则召回 TopK 范围，避免默认值大于最大值。"""
        if self.rule_recall_default_top_k > self.rule_recall_max_top_k:
            raise ValueError("RULE_RECALL_DEFAULT_TOP_K 不能大于 RULE_RECALL_MAX_TOP_K。")

        return self

    @property
    def uploads_dir(self) -> Path:
        """上传文件目录。"""
        return self.audit_storage_dir / "uploads"

    @property
    def outputs_dir(self) -> Path:
        """结果导出目录。"""
        return self.audit_storage_dir / "outputs"

    @property
    def database_path(self) -> Path:
        """SQLite 数据库文件路径。"""
        return self.audit_storage_dir / "audit_agent.db"

@lru_cache
def get_settings() -> Settings:
    """缓存配置对象，避免每次调用都重新读取环境变量。"""
    return Settings()


def ensure_storage_dirs(settings: Settings | None = None) -> None:
    """确保本地存储目录存在。"""
    current_settings = settings or get_settings()
    current_settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    current_settings.outputs_dir.mkdir(parents=True, exist_ok=True)
