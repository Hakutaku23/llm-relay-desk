"""Deterministic local mock upstream for development and tests."""

from .app import create_app

__all__ = ["create_app"]
