from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
