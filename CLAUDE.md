# CLAUDE.md

Project context for Claude Code. Read this before making changes.

## What this is

A **Streamlit prototype (ALPHA)** that analyzes a photo of a hand-drawn analog
clock with the **Claude Opus 4.8 vision API** using established Clock Drawing
Test (CDT) scoring frameworks. It is a screening-awareness demo, **not** a
diagnostic tool and **not** a validated instrument.

## Hard invariants — do not break these without an explicit decision from the user

1. **Stores nothing.** No database, no persistent CSV, no retained images. The
   app writes the result JSON and the drawing to temp files only to display
   real filenames + contents, then deletes them and confirms deletion. If asked
   to add real persistence, treat it as a deliberate architecture change and
   surface the privacy/compliance implications first.
2. **Not a diagnosis.** Never let UI copy, prompts, or output claim to diagnose
   Alzheimer's, dementia, Parkinson's, or any condition. Keep the loud ALPHA /
   synthetic-data / not-a-medical-device banner and the non-diagnostic framing.
3. **Synthetic data only.** This build is for testing with fake inputs.
4. **Filenames = `<ip>__<UTC-datetime>`.** IP + date is the shared base for the
   drawing (`.png/.jpg/...`) and JSON (`.json`). IP is captured ONLY to name the
   (transient) files and appears in the shown output. Resolution lives in the
   pure, tested `resolve_client_ip()`: `st.context.ip_address` → forwarded
   header (`X-Forwarded-For`/`X-Real-Ip`, for reverse proxies) → `127.0.0.1` for
   localhost runs (Streamlit reports `ip_address=None` for loopback clients, so
   without this fallback a local test would record `"unknown"`) → `"unknown"`.
5. **Model is pinned** to `claude-opus-4-8` (`DEFAULT_MODEL` in
   `clock_analyzer.py`). It supports vision via the standard Messages API.
6. **Scoring/interpretation must stay grounded** in the cited literature (see
   README "References"). Don't invent new "diagnostic" scales.

## Architecture / file map

| File | Responsibility |
|------|----------------|
| `app.py` | Streamlit UI: disclaimer/ack gate, synthetic inputs, the **fixed 11:10 drawing instruction**, capture, analyze, render (incl. "Scores at a glance" + a non-diagnostic "What to do with this" panel), **Start over**. UI only — keep logic thin. Capture widgets are keyed with a `form_nonce`; `_start_over()` clears session state and bumps the nonce so the held photo/upload is dropped, not just unread. |
| `clock_analyzer.py` | Builds the CDT prompt, calls Claude Opus 4.8 (vision), parses JSON. Scores MoCA (0–3), Shulman (1–5), Sunderland (1–10), **ACE-III clock (0–5)**, and the **Mendez CDIS (20 items, 0–20)**; the ACE-III/Mendez criteria live in `_ACE3_RULES` / `_MENDEZ_RULES`. The prompt reads hands by **length** — hour = the shorter hand, minute = the longer hand — and marks the time ambiguous if the hands aren't two distinguishable lengths. The `anthropic` SDK is imported lazily inside `analyze_clock` so the module imports without the SDK. |
| `scoring_utils.py` | Pure helpers (`compute_time_correct`, `camera_can_work`) + the standardized-time constants (`STANDARD_HOUR/MINUTE`, `STANDARD_TIME_SPOKEN`). No Streamlit/SDK imports — unit-test here. |
| `components/clock_camera/` | In-browser countdown auto-capture custom component (no npm build): live rear-camera preview → **Start** runs a 5→1 countdown → auto-grabs a frame → returns a `data:` URL that `normalize_image()` decodes. `__init__.py` wraps `declare_component`; `index.html` is the static frontend. Falls back to `back_camera_input`/`st.camera_input` if it can't import. |
| `transient_output.py` | IP+date filename construction; write/delete temp files. No persistence. |
| `test_basic.py` | pytest for the pure logic (runs without Streamlit, SDK, or an API key). Lives at the repo root; imports the top-level modules directly. |
| `logos/` | Header branding (DataTecnica, Center for Alzheimer's, VCU). UI only; `render_header_logos()` in `app.py` skips any missing file. |

When adding logic, prefer putting testable pieces in `scoring_utils.py` or
`transient_output.py`, and keep `app.py` as a thin UI layer.

**Camera:** browsers allow `st.camera_input` only in a secure context (HTTPS or
localhost). `camera_decision(server_ok, client_status)` (pure, tested) is
deliberately **optimistic**: the only thing that hides the camera is an insecure
context (`camera_can_work(st.context.url)` is False, or the client probe returns
`"insecure"`). It does NOT hide on `"nocam"`/`"unsupported"`/`"error"`, because
`enumerateDevices()` reports no `videoinput` *before* the user grants camera
permission (notably on mobile Safari), so trusting it false-negatives a working
camera over the web. The Upload tab is always present as a fallback. The
client-side probe (`streamlit-javascript`, optional) now only matters for the
insecure signal. Don't "fix" a phone camera that fails on a `http://<lan-ip>`
URL — that's the browser rule; use HTTPS/a tunnel.

**Command time is FIXED, not the current time:** the person is asked to draw the
standardized CDT time **"ten past eleven" (11:10)** — `STANDARD_HOUR/MINUTE` and
`STANDARD_TIME_SPOKEN` in `scoring_utils.py`. This is the convention the Mendez
CDIS is built around (its item 4 keys on the "2", item 9 on the "11"). There is
**no** time picker; don't reintroduce one without a deliberate decision. (The
older `resolve_local_now()` / `to_24h` / `to_12h` helpers remain in
`scoring_utils.py` — still pure and tested — but `app.py` no longer drives a
picker with them.)

Capture defaults to the **rear camera** via the `components/clock_camera`
countdown component (then `streamlit-back-camera-input`, then `st.camera_input`)
so it points at the drawing, not the user's face. All sources are normalized to
`(bytes, mime)` by `normalize_image()` (pure, tested) — including the component's
`data:` URL — so keep that the single chokepoint; new capture sources shouldn't
fan out type handling.

## Run

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # or copy .env.example -> .env, or paste in the sidebar
streamlit run app.py
```

## Test

```bash
pip install -r requirements-dev.txt
pytest -q
```

Tests must not require network, an API key, or Streamlit. Don't call the real
API in tests — if you need to exercise `analyze_clock`, mock the SDK client.

## Conventions

- Python 3.10+, standard library + the deps in `requirements*.txt`.
- Keep docstrings; keep the references block in `clock_analyzer.py` in sync with
  the README.
- Don't commit secrets or any `data/`-style output (see `.gitignore`).
- Copyright: when touching the README references, link to DOIs / PubMed; don't
  paste article abstracts or long quotations.
