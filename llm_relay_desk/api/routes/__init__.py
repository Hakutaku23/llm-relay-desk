from .admin import router as admin_router
from .monitor import router as monitor_router
from .native import router as native_router
from .openai import router as openai_router
from .system import router as system_router

__all__ = [
    "admin_router",
    "monitor_router",
    "native_router",
    "openai_router",
    "system_router",
]
