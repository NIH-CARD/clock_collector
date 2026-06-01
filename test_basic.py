"""
Tests for the pure logic. These run without Streamlit, the Anthropic SDK, an
API key, or network access.

    pytest -q
"""

import os

from scoring_utils import (
    compute_time_correct, to_24h, to_12h, fmt_12h, resolve_client_ip,
)
from clock_analyzer import _extract_json, build_user_prompt
import transient_output as tio


# --------------------------------------------------------------------------- #
# compute_time_correct
# --------------------------------------------------------------------------- #
def test_exact_match():
    assert compute_time_correct(11, 10, {"readable": True, "hour": 11, "minute": 10}) is True


def test_12h_equivalence():
    # 23:10 drawn on a 12-hour face as 11:10 should match
    assert compute_time_correct(23, 10, {"readable": True, "hour": 11, "minute": 10}) is True


def test_wrong_hour():
    assert compute_time_correct(11, 10, {"readable": True, "hour": 4, "minute": 10}) is False


def test_minute_wrap_tolerance():
    # target :00, drew :58 -> within +/-5 wrapping the hour
    assert compute_time_correct(3, 0, {"readable": True, "hour": 3, "minute": 58}) is True


def test_minute_out_of_tolerance():
    assert compute_time_correct(3, 0, {"readable": True, "hour": 3, "minute": 30}) is False


def test_unreadable_returns_none():
    assert compute_time_correct(3, 0, {"readable": False}) is None
    assert compute_time_correct(3, 0, None) is None
    assert compute_time_correct(3, 0, {"readable": True, "hour": None, "minute": 10}) is None


# --------------------------------------------------------------------------- #
# 12-hour <-> 24-hour conversion
# --------------------------------------------------------------------------- #
def test_to_24h_meridiem_edges():
    assert to_24h(12, "AM") == 0
    assert to_24h(12, "PM") == 12
    assert to_24h(1, "AM") == 1
    assert to_24h(1, "PM") == 13
    assert to_24h(11, "PM") == 23


def test_to_12h_roundtrips():
    for h24 in range(24):
        h12, mer = to_12h(h24)
        assert 1 <= h12 <= 12
        assert to_24h(h12, mer) == h24


def test_fmt_12h():
    assert fmt_12h(13, 5) == "1:05 PM"
    assert fmt_12h(0, 0) == "12:00 AM"
    assert fmt_12h(12, 30) == "12:30 PM"


# --------------------------------------------------------------------------- #
# resolve_client_ip
# --------------------------------------------------------------------------- #
def test_ip_prefers_context_ip_address():
    assert resolve_client_ip("203.0.113.5", {}, "https://example.com") == "203.0.113.5"


def test_ip_uses_first_forwarded_when_no_context_ip():
    headers = {"X-Forwarded-For": "198.51.100.7, 10.0.0.1"}
    assert resolve_client_ip(None, headers, "https://example.com") == "198.51.100.7"
    assert resolve_client_ip(None, {"x-real-ip": "203.0.113.9"}, None) == "203.0.113.9"


def test_ip_forwarded_header_beats_localhost_fallback():
    # behind a proxy the websocket is loopback (ip_address None) but the real
    # client IP is in the header — that should win over the 127.0.0.1 fallback.
    headers = {"X-Forwarded-For": "203.0.113.9"}
    assert resolve_client_ip(None, headers, "http://localhost:8501") == "203.0.113.9"


def test_ip_localhost_falls_back_to_loopback():
    for url in ("http://localhost:8501", "http://127.0.0.1:8501/", "http://[::1]:8501"):
        assert resolve_client_ip(None, {}, url) == "127.0.0.1"


def test_ip_unknown_when_nothing_available():
    assert resolve_client_ip(None, {}, "https://example.com") == "unknown"
    assert resolve_client_ip(None, {}, None) == "unknown"


# --------------------------------------------------------------------------- #
# _extract_json
# --------------------------------------------------------------------------- #
def test_extract_plain_json():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_in_code_fence_with_prose():
    text = 'Sure!\n```json\n{"x": {"y": [1, 2, 3]}}\n```\nthanks'
    assert _extract_json(text)["x"]["y"] == [1, 2, 3]


def test_extract_json_with_trailing_text():
    assert _extract_json('{"ok": true} and then some noise') == {"ok": True}


# --------------------------------------------------------------------------- #
# build_user_prompt
# --------------------------------------------------------------------------- #
def test_user_prompt_includes_target_time_and_inputs():
    p = build_user_prompt(11, 10, "72", "No known concerns")
    assert "11:10" in p
    assert "72" in p
    assert "No known concerns" in p


# --------------------------------------------------------------------------- #
# transient_output: filenames + write/delete cycle
# --------------------------------------------------------------------------- #
def test_filenames_are_filesystem_safe():
    for ip in ["203.0.113.7", "2001:db8::1", "10.0.0.1, 203.0.113.9", "unknown"]:
        base = tio.base_name(ip)
        for name in (tio.json_filename(base), tio.image_filename(base, "png")):
            assert "/" not in name and "\\" not in name and ":" not in name
            assert " " not in name


def test_write_show_delete_cycle(tmp_path, monkeypatch):
    # redirect temp dir so the test is self-contained
    monkeypatch.setattr(tio.tempfile, "gettempdir", lambda: str(tmp_path))
    base = tio.base_name("203.0.113.7")
    jpath = tio.write_temp_text(tio.json_filename(base), tio.to_json_text({"k": "v"}))
    ipath = tio.write_temp_bytes(tio.image_filename(base, "png"), b"\x89PNG fake")
    assert os.path.exists(jpath) and os.path.exists(ipath)
    assert tio.delete_file(jpath) is True
    assert tio.delete_file(ipath) is True
    assert not os.path.exists(jpath) and not os.path.exists(ipath)
    # deleting a missing file is safe
    assert tio.delete_file(jpath) is True
