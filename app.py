"""
app.py — Clock Drawing Screening (ALPHA, testing only)
------------------------------------------------------
This prototype STORES NOTHING. It captures the client IP and the date only to
NAME the result files (drawing + JSON), writes those files to a temporary
location so it can show their names and contents, then deletes them
immediately. Intended for testing with SYNTHETIC data only.

Flow:
  1. Loud alpha / no-storage / synthetic-data disclaimer + acknowledgement.
  2. Inputs (synthetic): age, cognitive status. The drawing target is the FIXED
     standardized CDT time "ten past eleven" (11:10), read aloud to the person.
  3. Capture: photo (camera / countdown auto-capture) or upload of the clock.
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
    fmt_12h, resolve_client_ip, STANDARD_HOUR, STANDARD_MINUTE, STANDARD_TIME_SPOKEN,
    score_rows, mendez_failed_labels, detail_lines, format_depicted,
)

# Optional client-side camera probe. If the package isn't installed the app
# still works — it just falls back to the server-side secure-context check.
try:
    from streamlit_javascript import st_javascript
    _HAS_JS_BRIDGE = True
except Exception:
    _HAS_JS_BRIDGE = False

# In-browser countdown auto-capture component (live preview -> 5s countdown ->
# auto-grab -> returns a data: URL). Optional — falls back to the rear-camera /
# stock camera widgets below if it can't be imported.
try:
    from components.clock_camera import clock_camera_input
    _HAS_CLOCK_CAMERA = True
except Exception:
    _HAS_CLOCK_CAMERA = False

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
    """True only when a NON-EMPTY ANTHROPIC_API_KEY secret is configured."""
    try:
        return bool(str(st.secrets.get("ANTHROPIC_API_KEY", "")).strip())
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
        "scoring (MoCA clock item, Shulman, Sunderland, ACE-III, Mendez CDIS, "
        "qualitative error analysis) with help from an AI model. It **cannot** "
        "identify "
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

st.header("2. What to ask the person to draw")
# Fixed, standardized Clock Drawing Test command time (not the current time): a
# spoken target embeds temporal-abstraction info the way clinical screeners do.
target_hour, target_minute = STANDARD_HOUR, STANDARD_MINUTE
_h12 = target_hour % 12 or 12
st.markdown(
    "Read this instruction aloud to the person, exactly as written:\n\n"
    f"> ### “Please draw a clock. Draw a circle, put in all the numbers from 1 "
    f"to 12, and set the time to {target_minute} past {_h12} ({STANDARD_TIME_SPOKEN}).”"
)
st.caption(
    f"The drawing is checked against the standardized CDT time "
    f"**{fmt_12h(target_hour, target_minute)}** — the same target used by the "
    "Mendez CDIS. Don't substitute the current time."
)

st.header("3. Take a picture of your clock")
st.markdown("#### 📷 When the drawing is finished, take a picture of it.")
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
    tab_cam, tab_upload = st.tabs(["📷 Camera", "📁 Upload a photo"])
    with tab_cam:
        if _HAS_CLOCK_CAMERA:
            st.markdown(
                "**Point the rear camera at the whole clock.** Press "
                "**Start countdown** — it counts **5 → 1** and takes the picture "
                "for you. (Or press **Take photo now** to snap it yourself.)"
            )
            cam_raw = clock_camera_input(key=f"cc_{nonce}")
        elif _HAS_BACK_CAMERA:
            st.caption("Uses your device's rear camera when available. Tap the video to capture.")
            cam_raw = back_camera_input(key=f"cam_{nonce}")
        else:
            cam_raw = st.camera_input("Hold the clock up to the camera", key=f"cam_{nonce}")
    with tab_upload:
        st.caption("No camera? Take a photo another way and upload it here.")
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

    # derive the time-accuracy check on our side ("or {}": the model may send a
    # null depicted_time, for which .get(..., {}) would still return None)
    depicted = analysis.get("depicted_time") or {}
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
        },
        "time_check": {
            "target": fmt_12h(target_hour, target_minute),
            "depicted": format_depicted(depicted),
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
        "analysis": analysis_clean,
        "time_check": payload["time_check"],
    }


# --------------------------------------------------------------------------- #
# Results: print the JSON, then confirm deletion of both files
# --------------------------------------------------------------------------- #
def _render_next_steps() -> None:
    """A clearly non-diagnostic 'what to do with this' panel. Deliberately names
    no condition and gives no clinical cut-off — it points back to a qualified
    clinician and lists the many non-cognitive factors that affect a drawing."""
    with st.container(border=True):
        st.markdown(
            "#### What to do with this result\n"
            "- 🩺 **This is not a diagnosis.** It is an automated screening-"
            "awareness observation only. A clock drawing on its own cannot "
            "identify any medical condition.\n"
            "- 👩‍⚕️ **If you have concerns about thinking or memory** — your "
            "own or someone you care for — share them with a **qualified "
            "healthcare provider**, who can decide whether a full evaluation is "
            "appropriate. Bring examples of any day-to-day changes you've "
            "noticed.\n"
            "- ✏️ **Many non-cognitive things change a clock drawing:** eyesight, "
            "hand or motor control, the pen and paper, arthritis, tiredness, "
            "language, education, and photo quality. A low score here is not "
            "proof of anything.\n"
            "- 🚑 This tool is **not** for emergencies. For urgent symptoms "
            "(sudden confusion, weakness, trouble speaking), seek medical care "
            "right away."
        )


def render_result(r: dict) -> None:
    a = r.get("analysis") or {}
    st.header("Result")
    st.warning(
        "Automated **screening observation, not a diagnosis** — and this is an "
        "**alpha** running on **synthetic test data.**"
    )

    if not a.get("clock_detected", True):
        st.error("No clock could be detected in the image.")

    if r.get("image"):
        st.image(r["image"], caption=f"Drawing — `{r['image_filename']}` (not stored)", width=320)

    # 1) Quick description of what was drawn
    if a.get("clock_description"):
        st.subheader("What was drawn")
        st.write(a["clock_description"])

    # 2) Time check + the score tables
    tc = r.get("time_check") or {}
    if tc:
        mark = {True: "✅ correct", False: "❌ off-target"}.get(tc.get("time_correct"), "❔ unclear")
        st.caption(f"Requested **{tc.get('target')}** · drawn **{tc.get('depicted')}** — {mark}")

    st.subheader("Scores")
    st.caption("Published CDT scales — higher is better. Screening scores, **not** a diagnosis or cut-off.")
    st.table(score_rows(a))
    failed = mendez_failed_labels(a)
    if failed:
        with st.expander(f"Mendez CDIS — {len(failed)} item(s) not met"):
            st.markdown("\n".join(f"- {label}" for label in failed))

    # 3) Rationale
    if a.get("overall_summary"):
        st.subheader("Rationale")
        st.write(a["overall_summary"])

    notes = detail_lines(a)
    if notes:
        with st.expander("More detail (per-scale notes, observations, errors)"):
            st.markdown("\n".join(notes))

    _render_next_steps()

    st.subheader("Result files (transient — not stored)")
    st.caption(f"Captured IP (used only to name files): `{r['ip']}`")
    st.write(f"**Drawing file:** `{r['image_filename']}`")
    st.write(f"**JSON file:** `{r['json_filename']}`")
    with st.expander("Raw result JSON (the transient file's contents)"):
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
