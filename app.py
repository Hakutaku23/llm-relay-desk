from __future__ import annotations

import multiprocessing

from llm_relay_desk import create_app
from llm_relay_desk.settings import Settings

settings = Settings.from_env()
app = create_app(settings)


if __name__ == "__main__":
    import uvicorn

    multiprocessing.freeze_support()
    uvicorn.run(
        "app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )
