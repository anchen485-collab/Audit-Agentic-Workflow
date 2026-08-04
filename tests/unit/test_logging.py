from io import StringIO

from app.infrastructure.settings import Settings
from app.observability.logging import configure_logging, get_audit_logger


def test_configure_logging_rebinds_console_handler_to_current_stdout(monkeypatch):
    """重复初始化日志时，应该把控制台 handler 绑定到当前 stdout。"""
    first_stdout = StringIO()
    second_stdout = StringIO()
    settings = Settings(_env_file=None)

    monkeypatch.setattr("sys.stdout", first_stdout)
    configure_logging(settings)
    get_audit_logger("test").info("first message")

    monkeypatch.setattr("sys.stdout", second_stdout)
    configure_logging(settings)
    get_audit_logger("test").info("second message")

    assert "first message" in first_stdout.getvalue()
    assert "second message" in second_stdout.getvalue()
    assert "second message" not in first_stdout.getvalue()
