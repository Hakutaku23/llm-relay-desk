from __future__ import annotations

from typing import TYPE_CHECKING

from .settings import APP_VERSION

if TYPE_CHECKING:
    from fastapi import FastAPI
    from .settings import Settings


def create_app(settings: "Settings | None" = None) -> "FastAPI":
    from .application import create_app as application_factory

    return application_factory(settings)


__all__ = ["APP_VERSION", "create_app"]
