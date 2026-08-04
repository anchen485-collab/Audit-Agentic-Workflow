from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from app.api.routes import health_router, review_router, router
from app.observability.logging import configure_logging


def create_app() -> FastAPI:
    """创建 FastAPI 应用。"""
    configure_logging()
    app = FastAPI(title="Audit Agent API", version="0.1.0")
    static_dir = Path(__file__).resolve().parents[1] / "static"

    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.include_router(router)
    app.include_router(review_router)
    app.include_router(health_router)

    @app.get("/")
    def audit_workbench() -> FileResponse:
        """审批工作台页面。"""
        return FileResponse(static_dir / "index.html")

    @app.get("/health")
    def health() -> dict[str, str]:
        """健康检查接口。"""
        return {"status": "ok"}

    return app


app = create_app()
