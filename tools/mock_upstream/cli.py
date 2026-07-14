from __future__ import annotations

import argparse
from collections.abc import Sequence

import uvicorn


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the LLM Relay Desk mock upstream")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=18000, type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    uvicorn.run(
        "tools.mock_upstream.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        log_level="info",
        access_log=False,
    )
