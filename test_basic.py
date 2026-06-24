"""
Tests for the pure logic. These run without Streamlit, the Anthropic SDK, an
API key, or network access.

    pytest -q
"""

import os

from datetime import datetime, timezone

from scoring_utils import (
    compute_time_correct, to_24h, to_12h, fmt_12h, resolve_client_ip,
    camera_decision, resolve_local_now,
    STANDARD_HOUR, STANDARD_MINUTE, STANDARD_TIME_SPOKEN,
    fmt_score, score_rows, mendez_failed_labels, detail_lines, format_depicted,
    MENDEZ_ITEM_LABELS,
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
# camera_decision — optimistic: only an insecure context hides the camera
# --------------------------------------------------------------------------- #
def test_camera_hidden_only_on_insecure():
    # insecure server context -> upload only
    assert camera_decision(False, None)[0] is False
    assert camera_decision(False, "ok")[0] is False
    # client probe says insecure -> upload only
    assert camera_decision(True, "insecure")[0] is False


def test_camera_shown_for_everything_else():
    # pending, ok, and — crucially — a pre-permission "nocam"/"unsupported"/"error"
    # must NOT hide a camera that would actually work.
    for status in (None, "ok", "nocam", "unsupported", "error", "weird"):
        show, msg = camera_decision(True, status)
        assert show is True and msg is None


# --------------------------------------------------------------------------- #
# resolve_local_now — user's timezone, not the server's
# --------------------------------------------------------------------------- #
def test_local_now_uses_iana_timezone():
    utc = datetime(2026, 6, 1, 16, 30, tzinfo=timezone.utc)
    # America/New_York is UTC-4 in June (EDT) -> 12:30
    local = resolve_local_now("America/New_York", None, utc)
    assert (local.hour, local.minute) == (12, 30)


def test_local_now_falls_back_to_offset():
    utc = datetime(2026, 6, 1, 16, 30, tzinfo=timezone.utc)
    # JS getTimezoneOffset for UTC-5 is +300; local = UTC - 300min = 11:30
    local = resolve_local_now(None, 300, utc)
    assert (local.hour, local.minute) == (11, 30)


def test_local_now_no_signal_returns_utc():
    utc = datetime(2026, 6, 1, 16, 30, tzinfo=timezone.utc)
    assert resolve_local_now(None, None, utc) == utc
    # an invalid IANA name falls through (here, to UTC since no offset given)
    assert resolve_local_now("Not/AZone", None, utc) == utc


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


def test_standard_time_constant():
    # the app fixes the command time to the standardized CDT value
    assert (STANDARD_HOUR, STANDARD_MINUTE) == (11, 10)
    assert STANDARD_TIME_SPOKEN == "ten past eleven"


def test_user_prompt_includes_ace3_and_mendez():
    p = build_user_prompt(STANDARD_HOUR, STANDARD_MINUTE, "65", "No known concerns")
    # the two added rubrics are present in both the instructions and the schema
    assert "ACE-III clock item" in p and "ace3_clock" in p
    assert "Mendez CDIS" in p and "mendez_cdis" in p
    # all 20 Mendez items are enumerated
    for i in range(1, 21):
        assert f"\n  {i}." in p
    # the feedback-specific cues: numbers-outside penalty + hand differentiation
    assert "TOTALLY WITHIN" in p
    assert "visibly longer" in p


def test_user_prompt_requests_clock_description():
    p = build_user_prompt(STANDARD_HOUR, STANDARD_MINUTE, "65", "No known concerns")
    assert "clock_description" in p


# --------------------------------------------------------------------------- #
# Result formatting helpers
# --------------------------------------------------------------------------- #
_SAMPLE = {
    "moca_clock": {"contour": 1, "numbers": 1, "hands": 0, "total": 2},
    "shulman_5point": {"score": 4, "rationale": "minor hand error"},
    "sunderland_10point": {"score": 8, "rationale": "mostly intact"},
    "ace3_clock": {"circle": 1, "numbers": 2, "hands": 1, "total": 4},
    "mendez_cdis": {"items": {str(i): 1 for i in range(1, 21)}, "total": 20},
    "qualitative_errors": ["planning"],
    "domain_observations": "good spatial layout",
    "literature_association_notes": "non-specific",
    "overall_summary": "A clear clock.",
}


def test_fmt_score_handles_missing():
    assert fmt_score(2, 3) == "2 / 3"
    assert fmt_score(None, 3) == "—"
    assert fmt_score("x", 3) == "—"


def test_score_rows_shape_and_values():
    rows = score_rows(_SAMPLE)
    assert [r["Scale"] for r in rows] == [
        "MoCA clock", "Shulman 5-point", "Sunderland 10-point",
        "ACE-III clock", "Mendez CDIS",
    ]
    by_scale = {r["Scale"]: r for r in rows}
    assert by_scale["MoCA clock"]["Score"] == "2 / 3"
    assert "hands 0" in by_scale["MoCA clock"]["Breakdown"]
    assert by_scale["ACE-III clock"]["Score"] == "4 / 5"
    assert by_scale["Mendez CDIS"]["Score"] == "20 / 20"


def test_score_rows_tolerates_empty_analysis():
    rows = score_rows({})
    assert all(r["Score"] == "—" for r in rows)
    rows_none = score_rows(None)
    assert len(rows_none) == 5


def test_mendez_failed_labels_lists_only_zeros():
    a = {"mendez_cdis": {"items": {str(i): 1 for i in range(1, 21)}}}
    a["mendez_cdis"]["items"]["4"] = 0
    a["mendez_cdis"]["items"]["8"] = 0
    failed = mendez_failed_labels(a)
    assert len(failed) == 2
    assert failed[0].startswith("#4.") and "ten-past" in failed[0]
    assert failed[1].startswith("#8.")
    # a perfect score yields nothing
    assert mendez_failed_labels(_SAMPLE) == []


def test_detail_lines_includes_present_fields_only():
    lines = detail_lines(_SAMPLE)
    joined = "\n".join(lines)
    assert "Shulman" in joined and "minor hand error" in joined
    assert "Qualitative errors" in joined and "planning" in joined
    assert "Domain observations" in joined
    # nothing fabricated for an empty analysis
    assert detail_lines({}) == []


def test_format_depicted():
    assert format_depicted({"readable": True, "hour": 11, "minute": 10}) == "11:10"
    assert format_depicted({"readable": True, "hour": 9, "minute": 5}) == "9:05"
    # the model may send a null hour/minute or readable=false -> never crash
    assert format_depicted({"readable": True, "hour": 11, "minute": None}) == "unclear"
    assert format_depicted({"readable": True, "hour": None, "minute": 10}) == "unclear"
    assert format_depicted({"readable": False}) == "unclear"
    assert format_depicted(None) == "unclear"


def test_mendez_labels_count_matches_items():
    # one display label per CDIS item — positional coupling guard
    assert len(MENDEZ_ITEM_LABELS) == 20
    # the 11:10 anchors line up with Mendez items 4 ('2') and 9 ('11')
    assert "2" in MENDEZ_ITEM_LABELS[3]
    assert "11" in MENDEZ_ITEM_LABELS[8]


def test_formatters_tolerate_wrong_typed_model_output():
    # model returns lists where dicts are expected -> must not raise
    bad = {"moca_clock": [1, 1, 1], "mendez_cdis": {"items": [0, 1]},
           "shulman_5point": "oops"}
    rows = score_rows(bad)
    assert len(rows) == 5 and all(r["Score"] == "—" for r in rows)
    assert mendez_failed_labels(bad) == []
    assert detail_lines(bad) == []


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
