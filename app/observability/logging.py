import logging
import sys

from app.infrastructure.settings import Settings, get_settings

AUDIT_LOGGER_NAME = "audit_agent"
LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def configure_logging(settings: Settings | None = None) -> logging.Logger:
    """初始化审批 Agent 控制台日志。"""
    current_settings = settings or get_settings()
    level = _resolve_log_level(current_settings.audit_log_level)
    logger = logging.getLogger(AUDIT_LOGGER_NAME)

    logger.setLevel(level)
    logger.propagate = False

    _remove_console_handlers(logger)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.setLevel(level)
    handler._audit_console_handler = True  # type: ignore[attr-defined]
    logger.addHandler(handler)

    return logger


def get_audit_logger(name: str) -> logging.Logger:
    """获取审批 Agent 子 logger。"""
    return logging.getLogger(f"{AUDIT_LOGGER_NAME}.{name}")


def _resolve_log_level(level_name: str) -> int:
    """把配置中的日志级别转换为 logging 常量。"""
    normalized_name = (level_name or "INFO").upper().strip()
    level = getattr(logging, normalized_name, None)

    if isinstance(level, int):
        return level

    return logging.INFO


def _remove_console_handlers(logger: logging.Logger) -> None:
    """移除旧控制台 handler，避免日志继续写到旧终端或后台重定向文件。"""
    for handler in list(logger.handlers):
        if isinstance(handler, logging.StreamHandler):
            logger.removeHandler(handler)
            handler.close()
