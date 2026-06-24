"""
scoring_utils.py
----------------
Pure, dependency-free helpers used by the app. Kept separate from app.py so the
logic can be unit-tested without importing Streamlit.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

# Browsers only allow camera access (getUserMedia) in a "secure context":
# HTTPS, or a localhost origin. These hosts count as localhost.
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}

# Standardized clinical command time. The drawer is asked to set the clock to
# "ten past eleven" (11:10) — the convention used by the Mendez CDIS (whose
# items key on the "11" hour hand and the "2" minute position) and a common CDT
# choice because it forces temporal abstraction (the "10" is at the 2, not the
# 10) and engages both visual hemifields.
STANDARD_HOUR = 11
STANDARD_MINUTE = 10
# Spoken form of the standard time, kept beside the numbers so the on-screen
# instruction and the target can't drift apart.
STANDARD_TIME_SPOKEN = "ten past eleven"


def camera_can_work(url: Optional[str]) -> bool:
    """Mirror the browser's secure-context rule for the camera.

    Given the URL the browser loaded (e.g. ``st.context.url``), return ``False``
    only when we can positively tell the page was served over plain HTTP to a
    non-localhost host — the one case where the browser is *guaranteed* to block
    the camera. In every other case (HTTPS, localhost, or unknown) return
    ``True`` and let the browser handle the permission prompt, so we never hide
    a camera that would actually work.
    """
    if not url:
        return True
    try:
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        host = (parsed.hostname or "").lower()
    except Exception:
        return True
    if scheme == "https":
        return True
    if host in LOCAL_HOSTS:
        return True
    if scheme == "http":  # http on a real host -> camera is blocked
        return False
    return True


# Messages shown when the camera path is unavailable, by cause.
CAMERA_MSG_HTTPS = (
    "📷 Camera capture needs a secure (HTTPS) connection, which isn't "
    "available here — please upload a photo instead."
)
CAMERA_MSG_NO_DEVICE = (
    "📷 No camera was detected on your device — please upload a photo instead."
)
CAMERA_MSG_UNAVAILABLE = (
    "📷 Camera capture isn't available in this browser — please upload a photo "
    "instead."
)


def camera_decision(server_ok: bool, client_status: Optional[str]):
    """Decide whether to show the camera, and which message to show if not.

    ``server_ok``: result of ``camera_can_work(url)`` (False == insecure context).
    ``client_status``: from the browser probe, one of
    ``"ok" | "nocam" | "insecure" | "unsupported" | "error"`` or ``None``
    (pending, or the JS bridge is unavailable).

    Returns ``(show_camera, message_or_None)``.

    Optimistic by design: the ONLY reason to hide the camera is an origin where
    the browser is guaranteed to block it — an insecure (non-HTTPS, non-local)
    context. The client ``enumerateDevices()`` probe is unreliable *before* the
    user grants camera permission — on mobile Safari especially it reports no
    ``videoinput`` even when a camera exists — so a ``"nocam"`` / ``"unsupported"``
    / ``"error"`` result must NOT hide a camera that would actually work. The
    Upload tab is always available as a fallback regardless.
    """
    if not server_ok:
        return (False, CAMERA_MSG_HTTPS)
    if client_status == "insecure":
        return (False, CAMERA_MSG_HTTPS)
    return (True, None)


def sniff_image_mime(data: bytes) -> Optional[str]:
    """Best-effort MIME from magic bytes."""
    if not data:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


def decode_data_url(value: str):
    """Decode a ``data:image/...;base64,...`` URL to ``(bytes, mime)`` or None."""
    if not isinstance(value, str) or not value.startswith("data:"):
        return None
    try:
        header, b64 = value.split(",", 1)
    except ValueError:
        return None
    mime = "image/png"
    body = header[len("data:"):]
    if body:
        mime = body.split(";", 1)[0] or mime
    import base64
    try:
        data = base64.b64decode(b64, validate=False)
    except Exception:
        return None
    if not data:
        return None
    return (data, sniff_image_mime(data) or mime or "image/png")


def normalize_image(value):
    """Normalize any of our capture sources to ``(bytes, mime)`` or None.

    Handles a Streamlit UploadedFile (``st.camera_input`` / ``st.file_uploader``;
    has ``getvalue``/``type``), a base64 data-URL string (``back_camera_input``),
    or raw ``bytes``.
    """
    if not value:
        return None
    getvalue = getattr(value, "getvalue", None)
    if callable(getvalue):
        data = getvalue()
        mime = getattr(value, "type", None) or sniff_image_mime(data) or "image/png"
        return (data, mime)
    if isinstance(value, str):
        return decode_data_url(value)
    if isinstance(value, (bytes, bytearray)):
        data = bytes(value)
        return (data, sniff_image_mime(data) or "image/png")
    return None


def _is_local_url(url: Optional[str]) -> bool:
    """True when ``url`` was loaded from a localhost/loopback host."""
    if not url:
        return False
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host in LOCAL_HOSTS


def resolve_client_ip(ip_address: Optional[str], headers, url: Optional[str]) -> str:
    """Best-effort client IP used only to name the (transient) result files.

    Precedence:
      1. ``st.context.ip_address`` — set for ordinary remote clients.
      2. The first proxy-forwarded address (``X-Forwarded-For`` / ``X-Real-Ip``),
         which is where the real client IP lives behind a reverse proxy (the
         proxy itself connects over loopback, so ``ip_address`` is None there).
      3. ``"127.0.0.1"`` when the page was loaded over a localhost URL — Streamlit
         reports ``ip_address=None`` for loopback clients, so without this a local
         run would otherwise be recorded as ``"unknown"``.
      4. ``"unknown"`` when nothing above applies.
    """
    if ip_address:
        return str(ip_address).strip()
    if headers:
        for key in ("X-Forwarded-For", "x-forwarded-for", "X-Real-Ip", "x-real-ip"):
            value = headers.get(key) if hasattr(headers, "get") else None
            if value:
                return str(value).split(",")[0].strip()
    if _is_local_url(url):
        return "127.0.0.1"
    return "unknown"


def to_24h(hour12: int, meridiem: str) -> int:
    """Convert a 12-hour clock hour (1-12) + 'AM'/'PM' to a 24-hour hour (0-23).

    12 AM -> 0, 12 PM -> 12, 1 PM -> 13, 11 PM -> 23.
    """
    h = int(hour12) % 12  # 12 -> 0
    if str(meridiem).strip().upper() == "PM":
        h += 12
    return h


def to_12h(hour24: int):
    """Inverse of :func:`to_24h`: 24-hour hour -> ``(hour12 in 1-12, 'AM'|'PM')``."""
    h = int(hour24) % 24
    meridiem = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return h12, meridiem


def fmt_12h(hour24: int, minute: int) -> str:
    """Human 12-hour label, e.g. ``(13, 5) -> '1:05 PM'``."""
    h12, meridiem = to_12h(hour24)
    return f"{h12}:{int(minute):02d} {meridiem}"


def resolve_local_now(tz_name, tz_offset_minutes, utc_now):
    """The user's *current local* time from the browser's timezone.

    Retained as a pure, tested helper; it is no longer wired to a UI picker (the
    command time is now fixed at 11:10 — see ``STANDARD_HOUR``/``STANDARD_MINUTE``).
    The server clock is useless for this — a deployed app runs in UTC, not the
    user's zone. Streamlit exposes the browser's zone via ``st.context``:

      - ``tz_name``: IANA name from ``st.context.timezone`` (e.g.
        ``"America/New_York"``) — unambiguous, preferred.
      - ``tz_offset_minutes``: ``st.context.timezone_offset`` — JavaScript
        ``getTimezoneOffset()`` semantics: minutes to ADD to local time to reach
        UTC, so ``local = UTC - offset`` (UTC-5 reports ``300``). Used as a
        fallback when the IANA name is missing/invalid.

    ``utc_now`` must be a timezone-aware UTC datetime. Returns an aware datetime
    in the user's zone, or ``utc_now`` unchanged when no signal is usable.
    """
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            return utc_now.astimezone(ZoneInfo(str(tz_name)))
        except Exception:
            pass
    if tz_offset_minutes is not None:
        try:
            from datetime import timedelta, timezone as _timezone
            tz = _timezone(timedelta(minutes=-int(tz_offset_minutes)))
            return utc_now.astimezone(tz)
        except Exception:
            pass
    return utc_now


def compute_time_correct(target_h: int, target_m: int, depicted: Optional[dict],
                         tol_min: int = 5) -> Optional[bool]:
    """Compare a target time to the time read off the drawing.

    Uses 12-hour equivalence (so 23:10 matches a clock showing 11:10) and a
    +/- ``tol_min`` minute tolerance that also wraps around the hour. Returns
    None when the depicted time is unreadable/missing.
    """
    if not depicted or not depicted.get("readable"):
        return None
    dh, dm = depicted.get("hour"), depicted.get("minute")
    if dh is None or dm is None:
        return None
    hour_ok = (int(dh) % 12) == (int(target_h) % 12)
    diff = abs(int(dm) - int(target_m))
    minute_ok = diff <= tol_min or diff >= (60 - tol_min)
    return bool(hour_ok and minute_ok)


# --------------------------------------------------------------------------- #
# Result formatting (pure) — turns the model's analysis dict into display rows.
# Kept here so app.py stays a thin UI layer and these are unit-testable.
# --------------------------------------------------------------------------- #

# Short labels for the 20 Mendez CDIS items (full criteria live in the prompt and
# the cited paper). Only failed items are surfaced, to keep the output concise.
# Position i-1 must correspond to Mendez item i in clock_analyzer._MENDEZ_RULES.
MENDEZ_ITEM_LABELS = [
    "attempt to indicate a time", "all marks are contour/hand/number",
    "closed figure, no gaps", "'2' indicated (ten-past)",
    "numbers form a circle", "≥3 quadrants have numbers",
    "numbers ordered clockwise", "numbers inside the figure",
    "'11' indicated (hour)", "all numbers 1–12 present",
    "no repeated numbers", "no numeral substitutions",
    "numbers don't exceed 12", "symbols equally near the edge",
    "≥7 symbols in sequence", "hands radiate from center",
    "one hand visibly longer", "exactly two separable hands",
    "hands inside the figure", "time indicated with hand(s)",
]
assert len(MENDEZ_ITEM_LABELS) == 20  # one label per CDIS item; keep in lockstep


def _as_dict(value) -> dict:
    """Model output coerced to a dict — guards against a null or wrong-typed
    field (the model JSON isn't schema-validated before we read it)."""
    return value if isinstance(value, dict) else {}


def fmt_score(value, maximum) -> str:
    """A scale score as ``"n / max"``, or ``"—"`` when missing/non-numeric."""
    try:
        return f"{int(value)} / {maximum}"
    except (TypeError, ValueError):
        return "—"


def _sub(value) -> str:
    """A sub-score as a string, or ``"—"`` when absent."""
    return str(value) if isinstance(value, int) else "—"


def format_depicted(depicted) -> str:
    """The drawn time as ``"h:mm"``, or ``"unclear"`` when the model couldn't read
    it. Tolerates a null/wrong-typed dict and a null hour or minute (all of which
    the schema permits) so the result view never crashes on model output."""
    d = _as_dict(depicted)
    if not d.get("readable") or d.get("hour") is None or d.get("minute") is None:
        return "unclear"
    try:
        return f"{int(d['hour'])}:{int(d['minute']):02d}"
    except (TypeError, ValueError):
        return "unclear"


def score_rows(analysis) -> list:
    """One row per CDT scale (``Scale`` / ``Score`` / ``Breakdown``) for a table."""
    a = _as_dict(analysis)
    moca = _as_dict(a.get("moca_clock"))
    ace3 = _as_dict(a.get("ace3_clock"))
    return [
        {"Scale": "MoCA clock", "Score": fmt_score(moca.get("total"), 3),
         "Breakdown": f"contour {_sub(moca.get('contour'))}, numbers "
                      f"{_sub(moca.get('numbers'))}, hands {_sub(moca.get('hands'))}"},
        {"Scale": "Shulman 5-point",
         "Score": fmt_score(_as_dict(a.get("shulman_5point")).get("score"), 5), "Breakdown": ""},
        {"Scale": "Sunderland 10-point",
         "Score": fmt_score(_as_dict(a.get("sunderland_10point")).get("score"), 10), "Breakdown": ""},
        {"Scale": "ACE-III clock", "Score": fmt_score(ace3.get("total"), 5),
         "Breakdown": f"circle {_sub(ace3.get('circle'))}, numbers "
                      f"{_sub(ace3.get('numbers'))}, hands {_sub(ace3.get('hands'))}"},
        {"Scale": "Mendez CDIS",
         "Score": fmt_score(_as_dict(a.get("mendez_cdis")).get("total"), 20),
         "Breakdown": "20 items, 1 pt each"},
    ]


def mendez_failed_labels(analysis) -> list:
    """Short labels of the Mendez items scored 0 (``"#n. label"``)."""
    items = _as_dict(_as_dict(_as_dict(analysis).get("mendez_cdis")).get("items"))
    return [f"#{i}. {MENDEZ_ITEM_LABELS[i - 1]}"
            for i in range(1, 21) if items.get(str(i)) == 0]


def detail_lines(analysis) -> list:
    """Markdown bullet lines for the 'More detail' expander: per-scale rationale
    and the model's narrative observations. Only includes fields that are present."""
    a = _as_dict(analysis)
    lines = []
    for key, label in (("shulman_5point", "Shulman"),
                       ("ace3_clock", "ACE-III"),
                       ("sunderland_10point", "Sunderland")):
        why = _as_dict(a.get(key)).get("rationale")
        if why:
            lines.append(f"- **{label}:** {why}")
    errors = a.get("qualitative_errors") or []
    if isinstance(errors, list) and errors:
        lines.append(f"- **Qualitative errors:** {', '.join(str(e) for e in errors)}")
    if a.get("domain_observations"):
        lines.append(f"- **Domain observations:** {a['domain_observations']}")
    if a.get("literature_association_notes"):
        lines.append(f"- **Literature notes (non-diagnostic):** {a['literature_association_notes']}")
    return lines
