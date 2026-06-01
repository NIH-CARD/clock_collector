"""
transient_output.py
--------------------
Builds result filenames from the client IP + a UTC date-time and writes the
drawing / JSON to TEMPORARY files so the app can show real filenames and
contents — then deletes them. **This module persists nothing.**

Invariant (see CLAUDE.md): filenames share a single base ``<ip>__<UTC-datetime>``;
the drawing keeps its image extension and the JSON gets ``.json``. The IP is
sanitized so the name is filesystem-safe on every OS (no ``:`` from IPv6, no
spaces/commas from a multi-hop ``X-Forwarded-For`` header, no path separators).

No Streamlit or SDK imports here, so the logic is unit-testable on its own.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone

# Anything outside this set is replaced with a hyphen when sanitizing an IP or
# extension, which strips ``:`` (IPv6 + time), ``/`` ``\`` (paths), spaces and
# commas (forwarded-for lists) — everything that could break a filename.
_UNSAFE = re.compile(r"[^A-Za-z0-9.\-]+")


def _sanitize(text: str) -> str:
    """Collapse any run of filesystem-unsafe characters into a single hyphen."""
    cleaned = _UNSAFE.sub("-", str(text or "")).strip("-")
    return cleaned or "unknown"


def _utc_stamp() -> str:
    """UTC date-time with no colons, so it is safe in a filename: 20260601T143005Z."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def base_name(ip: str) -> str:
    """Shared filename base ``<ip>__<UTC-datetime>`` (sanitized, no extension)."""
    return f"{_sanitize(ip)}__{_utc_stamp()}"


def json_filename(base: str) -> str:
    return f"{base}.json"


def image_filename(base: str, ext: str) -> str:
    ext = _sanitize(ext).lstrip(".") or "png"
    return f"{base}.{ext}"


def to_json_text(obj) -> str:
    """Pretty, deterministic JSON text for display and the optional download."""
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


def _temp_path(filename: str) -> str:
    # Re-read tempfile.gettempdir() each call so tests can monkeypatch it.
    return os.path.join(tempfile.gettempdir(), filename)


def write_temp_text(filename: str, text: str) -> str:
    path = _temp_path(filename)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def write_temp_bytes(filename: str, data: bytes) -> str:
    path = _temp_path(filename)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def delete_file(path: str) -> bool:
    """Delete ``path`` and confirm it's gone. Returns True if absent or removed,
    False only if removal failed and the file still exists."""
    try:
        os.remove(path)
    except FileNotFoundError:
        return True
    except OSError:
        return not os.path.exists(path)
    return not os.path.exists(path)
