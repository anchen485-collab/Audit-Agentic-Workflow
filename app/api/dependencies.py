from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.agents.evidence_agent import EvidenceProvider
from app.agents.llm_classification_provider import MockClassificationProvider, OpenAICompatibleClassificationProvider
from app.domain.models import CurrentUser
from app.infrastructure.evidence_provider import MockCompanyEvidenceProvider
from app.infrastructure.settings import Settings, get_settings
from app.infrastructure.website_provider import WebsiteCompanyProvider
from app.observability.logging import get_audit_logger

logger = get_audit_logger("api.dependencies")


def get_app_settings() -> Settings:
    """FastAPI 依赖：获取应用配置。"""
    return get_settings()


def get_current_user(
    settings: Annotated[Settings, Depends(get_app_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    """FastAPI 依赖：解析当前用户；本地未启用认证时返回开发用户。"""
    if not settings.auth_enabled:
        return CurrentUser(
            user_id="local_dev",
            tenant_id="default",
            roles=["admin", "uploader", "reviewer", "auditor"],
        )

    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少认证 token。",
        )

    user = _resolve_token_user(token=token, settings=settings)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证 token 无效。",
        )

    return user


def require_any_role(required_roles: set[str]) -> Callable:
    """生成角色校验依赖；admin 默认拥有所有权限。"""
    def dependency(
        current_user: Annotated[CurrentUser, Depends(get_current_user)],
    ) -> CurrentUser:
        if not current_user.has_any_role(required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="当前用户没有执行该操作的权限。",
            )

        return current_user

    return dependency


def get_rule_file_path() -> Path:
    """FastAPI 依赖：获取分类规则文件路径。"""
    return Path("data/rules/category_rules.json")


def _extract_bearer_token(authorization: str | None) -> str:
    """从 Authorization 请求头中提取 Bearer token。"""
    if not authorization:
        return ""

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return ""

    return token.strip()


def _resolve_token_user(token: str, settings: Settings) -> CurrentUser | None:
    """根据本地 token 映射生成用户上下文，格式：token:user_id:tenant_id:role1|role2。"""
    for token_config in settings.auth_tokens.split(";"):
        parts = [part.strip() for part in token_config.split(":")]
        if len(parts) != 4:
            continue

        configured_token, user_id, tenant_id, roles_text = parts
        if configured_token != token:
            continue

        roles = [
            role.strip()
            for role in roles_text.split("|")
            if role.strip()
        ]
        return CurrentUser(user_id=user_id, tenant_id=tenant_id, roles=roles)

    return None


def get_evidence_provider() -> EvidenceProvider:
    """根据配置选择企业证据 provider。"""
    settings = get_settings()
    provider_name = settings.company_provider.lower().strip()

    if provider_name == "mock":
        logger.info("企业证据 provider 已选择: mock")
        return MockCompanyEvidenceProvider("data/evidence/mock_company_evidence.json")

    if provider_name == "website":
        logger.info("企业证据 provider 已选择: website")
        return WebsiteCompanyProvider()

    logger.error("企业证据 provider 配置错误: provider=%s", settings.company_provider)
    raise ValueError(f"不支持的企业证据 provider：{settings.company_provider}")


def get_classification_provider():
    """根据配置选择 mock 或真实 LLM 判断 provider。"""
    settings = get_settings()

    if not settings.llm_enabled:
        logger.info("审批判断 provider 已选择: mock_classification")
        return MockClassificationProvider()

    logger.info(
        "审批判断 provider 已选择: openai_compatible model=%s base_url=%s",
        settings.llm_model,
        settings.llm_base_url,
    )
    return OpenAICompatibleClassificationProvider(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )
