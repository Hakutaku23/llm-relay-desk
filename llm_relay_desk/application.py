from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from llm_relay_desk.api.routes import (
    admin_router,
    monitor_router,
    native_router,
    openai_router,
    system_router,
)
from llm_relay_desk.api.routes.security import router as security_router
from llm_relay_desk.reasoning_middleware import VLLMReasoningResponseMiddleware
from llm_relay_desk.runtime import Runtime
from llm_relay_desk.settings import (
    APP_DESCRIPTION,
    APP_TITLE,
    APP_VERSION,
    Settings,
)

_UI_SCRIPTS = (
    '<script src="/ui-legacy/game-mode-controls.js?v=5.2.0"></script>',
    '<script src="/ui-legacy/security-controls.js?v=5.3.0"></script>',
)


def inject_ui_scripts(html: str) -> str:
    marker = "</body>"
    additions = [script for script in _UI_SCRIPTS if script.split('"')[1] not in html]
    if not additions:
        return html
    block = "\n  ".join(additions)
    if marker in html:
        return html.replace(marker, f"  {block}\n{marker}", 1)
    return f"{html}\n{block}\n"


def inject_mode_control_script(html: str) -> str:
    """Backward-compatible name retained for existing tests/imports."""
    return inject_ui_scripts(html)


def _read_legacy_ui_index(path: Path) -> str:
    html = path.read_text(encoding="utf-8").replace('"/ui/', '"/ui-legacy/')
    return inject_ui_scripts(html)


def _read_legacy_html(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace('"/ui/', '"/ui-legacy/')



def _cors_origins(port: int) -> list[str]:
    configured = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
    if configured:
        return [item.strip() for item in configured.split(",") if item.strip()]
    return [
        f"http://127.0.0.1:{port}",
        f"http://localhost:{port}",
    ]


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    runtime = Runtime.create(resolved_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        runtime.popup.configure(runtime.config_store.read())
        try:
            yield
        finally:
            runtime.popup.stop()

    app = FastAPI(
        title=APP_TITLE,
        version=APP_VERSION,
        description=APP_DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.runtime = runtime

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(resolved_settings.port),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Relay-Task-Type",
            "X-Relay-Admin-Test",
        ],
    )
    app.add_middleware(
        VLLMReasoningResponseMiddleware,
        runtime=runtime,
    )

    app.include_router(system_router)
    app.include_router(monitor_router)
    # Must be registered before the legacy admin router so the redacted
    # /admin/config handlers take precedence over the old plaintext handlers.
    app.include_router(security_router)
    app.include_router(admin_router)
    app.include_router(native_router)
    app.include_router(openai_router)

    legacy_index_path = resolved_settings.static_dir / "index.html"
    vue_index_path = resolved_settings.frontend_dist_dir / "index.html"

    @app.get("/ui", include_in_schema=False)
    async def ui_redirect() -> RedirectResponse:
        return RedirectResponse(url="/ui/")

    @app.get("/ui-legacy", include_in_schema=False)
    async def legacy_ui_redirect() -> RedirectResponse:
        return RedirectResponse(url="/ui-legacy/")

    @app.get("/ui-legacy/", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/ui-legacy/index.html", response_class=HTMLResponse, include_in_schema=False)
    async def legacy_ui_index() -> HTMLResponse:
        return HTMLResponse(
            content=_read_legacy_ui_index(legacy_index_path),
            headers={"Cache-Control": "no-cache"},
        )

    @app.get(
        "/ui-legacy/task-isolation.html",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    async def legacy_task_isolation() -> HTMLResponse:
        return HTMLResponse(
            content=_read_legacy_html(resolved_settings.static_dir / "task-isolation.html"),
            headers={"Cache-Control": "no-cache"},
        )

    def vue_index_response() -> FileResponse:
        if not vue_index_path.is_file():
            raise HTTPException(status_code=503, detail="Vue UI build is unavailable")
        return FileResponse(
            vue_index_path,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/ui/", include_in_schema=False)
    @app.get("/ui/index.html", include_in_schema=False)
    async def vue_ui_index() -> FileResponse:
        return vue_index_response()

    @app.get("/ui/{spa_path:path}", include_in_schema=False)
    async def vue_ui_path(spa_path: str) -> FileResponse:
        dist_root = resolved_settings.frontend_dist_dir.resolve()
        requested = (dist_root / spa_path).resolve()
        if not requested.is_relative_to(dist_root):
            raise HTTPException(status_code=404, detail="Static asset not found")
        if requested.is_file():
            return FileResponse(requested)
        if Path(spa_path).suffix:
            raise HTTPException(status_code=404, detail="Static asset not found")
        return vue_index_response()

    app.mount(
        "/monitor",
        StaticFiles(directory=resolved_settings.monitor_dir, html=True),
        name="monitor",
    )
    app.mount(
        "/ui-legacy",
        StaticFiles(directory=resolved_settings.static_dir, html=True),
        name="ui-legacy",
    )
    return app
