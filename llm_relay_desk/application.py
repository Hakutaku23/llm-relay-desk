from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from llm_relay_desk.api.routes import (
    admin_router,
    monitor_router,
    native_router,
    openai_router,
    system_router,
)
from llm_relay_desk.runtime import Runtime
from llm_relay_desk.settings import (
    APP_DESCRIPTION,
    APP_TITLE,
    APP_VERSION,
    Settings,
)

_MODE_CONTROL_SCRIPT = (
    '<script src="/ui/game-mode-controls.js?v=5.2.0"></script>'
)


def inject_mode_control_script(html: str) -> str:
    """Inject the v5.2 mode/protocol controls without replacing the existing Web UI.

    Keeping this as a separate script avoids copying and maintaining the large
    ``static/index.html`` and ``static/app.js`` files. Repeated injection is
    idempotent.
    """

    if "game-mode-controls.js" in html:
        return html
    marker = "</body>"
    if marker in html:
        return html.replace(marker, f"  {_MODE_CONTROL_SCRIPT}\n{marker}", 1)
    return f"{html}\n{_MODE_CONTROL_SCRIPT}\n"


def _read_ui_index(path: Path) -> str:
    return inject_mode_control_script(path.read_text(encoding="utf-8"))


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
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(system_router)
    app.include_router(monitor_router)
    app.include_router(admin_router)
    app.include_router(native_router)
    app.include_router(openai_router)

    index_path = resolved_settings.static_dir / "index.html"

    @app.get("/ui", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/ui/", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/ui/index.html", response_class=HTMLResponse, include_in_schema=False)
    async def ui_index() -> HTMLResponse:
        return HTMLResponse(
            content=_read_ui_index(index_path),
            headers={"Cache-Control": "no-cache"},
        )

    app.mount(
        "/monitor",
        StaticFiles(directory=resolved_settings.monitor_dir, html=True),
        name="monitor",
    )
    app.mount(
        "/ui",
        StaticFiles(directory=resolved_settings.static_dir, html=True),
        name="ui",
    )
    return app
