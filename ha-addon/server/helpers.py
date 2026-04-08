"""Shared helpers for the server — DRY utilities used across api.py, ui_api.py, main.py."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Optional

from aiohttp import web


def json_error(message: str, status: int = 400) -> web.Response:
    """Return a JSON error response."""
    return web.json_response({"error": message}, status=status)


def safe_resolve(config_dir: str | Path, filename: str) -> Optional[Path]:
    """Resolve a filename within config_dir, preventing path traversal.

    Returns the resolved Path if safe, or None if the path escapes config_dir.
    """
    base = Path(config_dir).resolve()
    path = (base / filename).resolve()
    try:
        path.relative_to(base)
    except ValueError:
        return None
    return path


def constant_time_compare(a: str, b: str) -> bool:
    """Timing-safe string comparison to prevent timing attacks on tokens."""
    return secrets.compare_digest(a.encode(), b.encode())


def clamp(value: int, min_val: int, max_val: int) -> int:
    """Clamp an integer to a range."""
    return max(min_val, min(max_val, value))
