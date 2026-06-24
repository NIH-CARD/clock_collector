"""
components.clock_camera
-----------------------
A self-contained Streamlit custom component that shows a live rear-camera
preview and captures a still photo of the drawing — either immediately or after
an on-screen 5-second countdown (so a person who can't reliably tap a button at
the right moment doesn't have to). The captured frame is returned to Python as a
``data:image/jpeg;base64,...`` URL.

That data-URL is exactly what :func:`scoring_utils.normalize_image` already
decodes (the same shape ``back_camera_input`` returns), so no new image handling
is needed downstream.

No npm build step: the frontend is a single static ``index.html`` that speaks
the Streamlit component postMessage protocol directly. Like the rest of the app,
this captures in the browser and hands the bytes to the session only — nothing
is stored.
"""

from __future__ import annotations

import os
from typing import Optional

import streamlit.components.v1 as components

_BUILD_DIR = os.path.dirname(os.path.abspath(__file__))
_component_func = components.declare_component("clock_camera", path=_BUILD_DIR)


def clock_camera_input(key: Optional[str] = None) -> Optional[str]:
    """Render the camera + countdown capture widget.

    Returns the captured photo as a ``data:`` URL string once the user has taken
    a picture, otherwise ``None`` (no capture yet, or the camera is unavailable —
    in which case the caller should rely on the Upload fallback).
    """
    return _component_func(key=key, default=None)
