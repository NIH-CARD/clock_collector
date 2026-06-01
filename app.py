"""
app.py — Clock Drawing Screening (ALPHA, testing only)
------------------------------------------------------
This prototype STORES NOTHING. It captures the client IP and the date only to
NAME the result files (drawing + JSON), writes those files to a temporary
location so it can show their names and contents, then deletes them
immediately. Intended for testing with SYNTHETIC data only.

Flow:
  1. Loud alpha / no-storage / synthetic-data disclaimer + acknowledgement.
  2. Inputs (synthetic): age, cognitive status, confirm current local time.
  3. Capture: photo (camera) or upload of a hand-drawn analog clock.
  4. Analyze with Claude Opus 4.8 against CDT scoring frameworks.
  5. Name files as <ip>__<date>.png / .json, print the JSON, then delete both
     files and confirm.

NOT a medical device. NOT a diagnosis.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import streamlit as st

import transient_output as tio
from clock_analyzer import analyze_clock
from scoring_utils import (
    compute_time_correct, camera_can_work, camera_decision, normalize_image,
    to_24h, to_12h, fmt_12h, resolve_client_ip,
)

# Optional client-side camera probe. If the package isn't installed the app
# still works — it just falls back to the server-side secure-context check.
try:
    from streamlit_javascript import st_javascript
    _HAS_JS_BRIDGE = True
except Exception:
    _HAS_JS_BRIDGE = False

# Optional rear-camera widget (defaults to the back camera on phones, which is
# better for privacy — it points at the drawing, not the user's face). Falls
# back to st.camera_input if the package isn't installed.
try:
    from streamlit_back_camera_input import back_camera_input
    _HAS_BACK_CAMERA = True
except Exception:
    _HAS_BACK_CAMERA = False

st.set_page_config(page_title="Clock Drawing Screening (ALPHA)", page_icon="🕐", layout="centered")

# Partner / sponsor logos shown in the header. Optional — silently skipped if a
# file is missing so the app never crashes over branding.
_LOGO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logos")
_HEADER_LOGOS = [
    "datatecnicahoriz_logo.png",
    "centerforalzheimersandrelateddementias_logo.png",
    "VCU_logo.png",
]


def render_header_logos() -> None:
    paths = [os.path.join(_LOGO_DIR, name) for name in _HEADER_LOGOS]
    paths = [p for p in paths if os.path.exists(p)]
    if not paths:
        return
    for col, path in zip(st.columns(len(paths)), paths):
        with col:
            st.image(path, width="stretch")

COGNITIVE_STATUS_OPTIONS = [
    "Prefer not to say",
    "No known concerns",
    "Mild concerns (mine or others')",
    "Diagnosed mild cognitive impairment",
    "Diagnosed dementia / neurodegenerative condition",
    "Other / unsure",
]

EXT_BY_MIME = {"image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif", "image/png": "png"}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _has_secret() -> bool:
    try:
        return "ANTHROPIC_API_KEY" in st.secrets
    except Exception:
        return False


def preconfigured_key_source():
    """Where a key is already available without the user typing one, or None.

    Returns "Streamlit secrets" or "environment" — used to decide whether to
    prompt in the sidebar. Secrets take precedence so a deployed app (key set in
    the Streamlit dashboard) runs without anyone pasting a key.
    """
    if _has_secret():
        return "Streamlit secrets"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "environment"
    return None


def get_api_key():
    if _has_secret():
        return st.secrets["ANTHROPIC_API_KEY"]
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    return st.session_state.get("api_key_input")


def get_client_ip() -> str:
    """Best-effort client IP, used only to name the transient result files.

    Gathers the context signals and delegates the precedence logic to the pure,
    tested ``resolve_client_ip`` (remote IP -> forwarded header -> 127.0.0.1 for
    localhost -> 'unknown'). Streamlit reports ``ip_address=None`` for loopback
    clients, so a local run is recorded as 127.0.0.1 rather than 'unknown'.
    """
    try:
        ctx = st.context
        ip = getattr(ctx, "ip_address", None)
        try:
            headers = dict(getattr(ctx, "headers", {}) or {})
        except Exception:
            headers = {}
        url = getattr(ctx, "url", None)
        return resolve_client_ip(ip, headers, url)
    except Exception:
        return "unknown"


def current_url():
    """The URL the browser loaded, used to tell whether the camera is allowed."""
    try:
        return getattr(st.context, "url", None)
    except Exception:
        return None


# JS run in the browser: secure-context + real-camera check. Returns one of
# "ok" | "nocam" | "insecure" | "unsupported" | "error".
_CAMERA_PROBE_JS = """await (async () => {
  try {
    if (!window.isSecureContext) return "insecure";
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return "unsupported";
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.some((d) => d.kind === "videoinput") ? "ok" : "nocam";
  } catch (e) {
    return "error";
  }
})()"""

_VALID_PROBE = {"ok", "nocam", "insecure", "unsupported", "error"}


def probe_camera_clientside():
    """Ask the browser whether a usable camera exists. Returns a status string,
    or None when pending (first run) or when the JS bridge isn't installed."""
    if not _HAS_JS_BRIDGE:
        return None
    try:
        result = st_javascript(_CAMERA_PROBE_JS, key="camera_probe")
    except Exception:
        return None
    return result if result in _VALID_PROBE else None


# --------------------------------------------------------------------------- #
# Header + ALPHA / no-storage disclaimer
# --------------------------------------------------------------------------- #
render_header_logos()

st.title("🕐 Clock Drawing Screening")

st.error(
    "🚧 **ALPHA — TESTING ONLY.** Use **synthetic / test data only.** "
    "This app **does not store any data**, and it is **not a medical device "
    "and not a diagnosis.**"
)

with st.container(border=True):
    st.markdown(
        "**About this prototype**\n\n"
        "- 🧪 **Alpha build.** Behavior and output may change; do not rely on it.\n"
        "- 🗄️ **No data is stored by this app.** Your IP address and the date are "
        "captured **only to name the result files** (the drawing and the JSON), "
        "and they appear in the output shown to you. After analysis the app "
        "displays those files, then **deletes them immediately** — nothing is "
        "written to a database or otherwise kept.\n"
        "- 🧍 **Use synthetic / fake inputs only.** Do not enter real people's "
        "information while testing.\n"
        "- 🩺 **Not diagnostic.** This applies published Clock Drawing Test "
        "scoring (MoCA clock item, Shulman, Sunderland, qualitative error "
        "analysis) with help from an AI model. It **cannot** identify "
        "Alzheimer's, dementia, Parkinson's, or any condition. Many "
        "non-cognitive factors (eyesight, hand control, the pen, photo quality) "
        "affect a clock drawing.\n"
        "- ⚖️ **Compliance is out of scope for this prototype.** Whoever "
        "deploys this for real use is responsible for HIPAA / GDPR / IRB and any "
        "appropriate storage — none of which exists here yet."
    )

# --------------------------------------------------------------------------- #
# Sidebar: API key only
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.subheader("Setup")
    if preconfigured_key_source():
        st.success("API key found")
    else:
        st.text_input(
            "Paste API key here",
            type="password",
            key="api_key_input",
            help="Your key is used only for this session and is not stored.",
        )
    st.divider()
    st.caption("🗄️ This alpha stores **nothing**. Files are named, shown, then deleted.")


# --------------------------------------------------------------------------- #
# Acknowledgement gate
# --------------------------------------------------------------------------- #
ack = st.checkbox(
    "I understand this is an **alpha for testing with synthetic data only**, "
    "that it **stores no data** (IP + date are used only to name the result "
    "files, which are then deleted), and that it is **not a diagnosis or "
    "medical device.**"
)

if not ack:
    st.info("Please read the notice above and check the box to begin.")
    st.stop()


# --------------------------------------------------------------------------- #
# Inputs (synthetic)
# --------------------------------------------------------------------------- #
st.header("1. Test subject (synthetic)")
st.caption("Enter fake / synthetic values — this is a test build.")
col_a, col_b = st.columns(2)
with col_a:
    age = st.number_input("Age (synthetic)", min_value=0, max_value=120, value=65, step=1)
with col_b:
    status = st.selectbox("Cognitive status (synthetic)", COGNITIVE_STATUS_OPTIONS, index=0)

st.header("2. The current time")
st.markdown(
    "Draw a **circular analog clock** and set the hands to **the time right "
    "now**, then confirm that time so the drawing can be checked against it."
)
now_local = datetime.now()
def_h12, def_meridiem = to_12h(now_local.hour)
col_h, col_m, col_ap = st.columns([2, 2, 1])
with col_h:
    sel_hour12 = st.selectbox("Hour", list(range(1, 13)), index=def_h12 - 1)
with col_m:
    sel_minute = st.number_input("Minute", min_value=0, max_value=59,
                                 value=now_local.minute, step=1, format="%02d")
with col_ap:
    sel_meridiem = st.selectbox("AM/PM", ["AM", "PM"], index=0 if def_meridiem == "AM" else 1)

target_hour = to_24h(sel_hour12, sel_meridiem)
target_minute = int(sel_minute)
st.caption(f"Checking the drawing against **{sel_hour12}:{target_minute:02d} {sel_meridiem}**.")

st.header("3. The drawing")
st.error(
    "🚫 **Do not include sensitive content in images — in particular your face.** "
    "Capture **only the clock drawing.** Use the rear camera and keep people, "
    "documents, and identifying details out of frame."
)
server_ok = camera_can_work(current_url())
client_status = probe_camera_clientside() if server_ok else None
show_camera, camera_message = camera_decision(server_ok, client_status)

# Capture widgets are keyed with a nonce so "Start over" can re-mount them empty
# (clearing session_state alone won't visually drop a held photo/upload).
nonce = st.session_state.get("form_nonce", 0)

if show_camera:
    st.markdown("Take a clear, well-lit photo of the finished clock, or upload one.")
    tab_cam, tab_upload = st.tabs(["📷 Camera", "📁 Upload"])
    with tab_cam:
        if _HAS_BACK_CAMERA:
            st.caption("Uses your device's rear camera when available. Tap the video to capture.")
            cam_raw = back_camera_input(key=f"cam_{nonce}")
        else:
            cam_raw = st.camera_input("Hold the clock up to the camera", key=f"cam_{nonce}")
    with tab_upload:
        up_raw = st.file_uploader(
            "Upload a photo", type=["png", "jpg", "jpeg", "webp"], key=f"upload_{nonce}"
        )
    raw_image = cam_raw or up_raw
else:
    st.info(camera_message)
    raw_image = st.file_uploader(
        "Upload a photo", type=["png", "jpg", "jpeg", "webp"], key=f"upload_{nonce}"
    )

# Normalize the chosen source (UploadedFile, data-URL string, or bytes) to bytes+mime.
image_payload = normalize_image(raw_image)

# --------------------------------------------------------------------------- #
# Analyze -> name (ip + date) -> print -> delete
# --------------------------------------------------------------------------- #
analyze = st.button("Analyze clock", type="primary", disabled=image_payload is None)

if analyze and image_payload is not None:
    api_key = get_api_key()
    if not api_key:
        st.error("No API key found. Paste one in the sidebar to continue.")
        st.stop()

    image_bytes, media_type = image_payload
    if media_type not in EXT_BY_MIME:
        media_type = "image/png"

    with st.spinner("The AI is analyzing your drawing…"):
        try:
            analysis = analyze_clock(
                image_bytes=image_bytes,
                media_type=media_type,
                target_hour=target_hour,
                target_minute=target_minute,
                api_key=api_key,
                self_reported_age=str(age),
                self_reported_status=status,
            )
        except Exception as exc:
            st.error(f"Sorry — the analysis failed: {exc}")
            st.stop()

    # derive the time-accuracy check on our side
    depicted = analysis.get("depicted_time", {})
    time_correct = compute_time_correct(target_hour, target_minute, depicted)
    if time_correct is None:
        time_correct = analysis.get("time_matches_target")

    # ---- build filenames from IP + date (shared base) ----
    ip = get_client_ip()
    base = tio.base_name(ip)
    ext = EXT_BY_MIME.get(media_type, "png")
    json_fn = tio.json_filename(base)
    img_fn = tio.image_filename(base, ext)

    # ---- build the result payload (no persistence; internal AI fields dropped) ----
    analysis_clean = {k: v for k, v in analysis.items() if k not in ("_raw_text", "_model")}
    payload = {
        "_app_meta": {
            "app": "Clock Drawing Screening — ALPHA (testing only)",
            "data_storage": "NONE — files are named, shown, then deleted. The app retains nothing.",
            "intended_data": "synthetic / test inputs only",
            "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "not_a_diagnosis": True,
        },
        "capture": {
            "client_ip": ip,
            "drawing_filename": img_fn,
            "json_filename": json_fn,
        },
        "inputs": {
            "self_reported_age": age,
            "self_reported_cognitive_status": status,
            "target_local_time": fmt_12h(target_hour, target_minute),
        },
        "time_check": {
            "target": fmt_12h(target_hour, target_minute),
            "depicted": (
                f"{depicted.get('hour')}:{depicted.get('minute'):02d}"
                if depicted.get("readable") and depicted.get("hour") is not None else "unclear"
            ),
            "time_correct": time_correct,
        },
        "analysis": analysis_clean,
    }

    # ---- write transient files (drawing + JSON) ONLY to show names/contents, then delete ----
    json_text = tio.to_json_text(payload)
    json_path = tio.write_temp_text(json_fn, json_text)
    img_path = tio.write_temp_bytes(img_fn, image_bytes)
    json_deleted = tio.delete_file(json_path)
    img_deleted = tio.delete_file(img_path)

    st.session_state["result"] = {
        "ip": ip,
        "json_filename": json_fn,
        "image_filename": img_fn,
        "json_text": json_text,
        "image": image_bytes,
        "image_mime": media_type,
        "json_deleted": json_deleted,
        "image_deleted": img_deleted,
        "screening_flag": analysis.get("screening_flag"),
        "summary": analysis.get("overall_summary"),
        "clock_detected": analysis.get("clock_detected", True),
    }


# --------------------------------------------------------------------------- #
# Results: print the JSON, then confirm deletion of both files
# --------------------------------------------------------------------------- #
def render_result(r: dict) -> None:
    st.header("Result")
    st.warning(
        "Automated **screening observation, not a diagnosis** — and this is an "
        "**alpha** running on **synthetic test data.**"
    )

    if not r.get("clock_detected", True):
        st.error("No clock could be detected in the image.")

    st.caption(f"Captured IP (used only to name files): `{r['ip']}`")

    if r.get("image"):
        st.image(r["image"], caption=f"Drawing — `{r['image_filename']}` (not stored)", width=320)
    if r.get("summary"):
        st.write(r["summary"])

    st.subheader("Result files (transient — not stored)")
    st.write(f"**Drawing file:** `{r['image_filename']}`")
    st.write(f"**JSON file:** `{r['json_filename']}`")
    st.code(r["json_text"], language="json")

    # let the tester save locally if they want; the app itself keeps nothing
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "Download JSON to your device (optional)",
            data=r["json_text"],
            file_name=r["json_filename"],
            mime="application/json",
        )
    with c2:
        st.download_button(
            "Download drawing to your device (optional)",
            data=r["image"],
            file_name=r["image_filename"],
            mime=r.get("image_mime", "image/png"),
        )

    if r.get("json_deleted") and r.get("image_deleted"):
        st.success(
            f"🗑️ Temporary files `{r['image_filename']}` and `{r['json_filename']}` "
            "were deleted. **No data was stored by this app.**"
        )
    else:
        missing = []
        if not r.get("image_deleted"):
            missing.append(r["image_filename"])
        if not r.get("json_deleted"):
            missing.append(r["json_filename"])
        st.error(
            "⚠️ Could not confirm deletion of: "
            + ", ".join(f"`{m}`" for m in missing)
            + ". Check the host's temp directory."
        )

    st.divider()
    st.button("🔄 Start over", type="primary", on_click=_start_over,
              help="Clear this result and all inputs and begin a fresh test.")


def _start_over() -> None:
    """Wipe every input, the captured/uploaded photo, and the result so the next
    run starts from a clean slate (the disclaimer gate included). The capture
    widgets are re-mounted under a fresh nonce so a held photo is dropped, not
    just unread. A key supplied via Streamlit secrets or the environment is
    unaffected — only a key typed into the sidebar is cleared. Streamlit reruns
    automatically after the callback."""
    next_nonce = st.session_state.get("form_nonce", 0) + 1
    st.session_state.clear()
    st.session_state["form_nonce"] = next_nonce


if "result" in st.session_state:
    render_result(st.session_state["result"])
