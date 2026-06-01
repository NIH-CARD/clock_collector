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
| `app.py` | Streamlit UI: disclaimer/ack gate, inputs (12-hour time picker), capture, analyze, render, **Start over**. UI only — keep logic thin. Capture widgets are keyed with a `form_nonce`; `_start_over()` clears session state and bumps the nonce so the held photo/upload is dropped, not just unread. |
| `clock_analyzer.py` | Builds the CDT prompt, calls Claude Opus 4.8 (vision), parses JSON. The prompt reads hands by **length** — hour = the shorter hand, minute = the longer hand — and marks the time ambiguous if the hands aren't two distinguishable lengths. The `anthropic` SDK is imported lazily inside `analyze_clock` so the module imports without the SDK. |
| `scoring_utils.py` | Pure helpers (`compute_time_correct`, `camera_can_work`). No Streamlit/SDK imports — unit-test here. |
| `transient_output.py` | IP+date filename construction; write/delete temp files. No persistence. |
| `test_basic.py` | pytest for the pure logic (runs without Streamlit, SDK, or an API key). Lives at the repo root; imports the top-level modules directly. |
| `logos/` | Header branding (DataTecnica, Center for Alzheimer's, VCU). UI only; `render_header_logos()` in `app.py` skips any missing file. |

When adding logic, prefer putting testable pieces in `scoring_utils.py` or
`transient_output.py`, and keep `app.py` as a thin UI layer.

**Camera:** browsers allow `st.camera_input` only in a secure context (HTTPS or
localhost). Detection is layered: `camera_can_work(st.context.url)` catches
plain-HTTP-on-a-remote-host server-side, and a client-side probe
(`streamlit-javascript`, optional — graceful fallback if absent) catches
no-camera/unsupported-browser. `camera_decision(server_ok, client_status)` (pure,
tested) maps both signals to (show_camera, message). Don't "fix" a phone camera
that fails on a `http://<lan-ip>` URL — that's the browser rule; use HTTPS/a tunnel.
Capture defaults to the **rear camera** (`streamlit-back-camera-input`, optional,
falls back to `st.camera_input`) so it points at the drawing, not the user's face.
All sources are normalized to `(bytes, mime)` by `normalize_image()` (pure, tested);
keep that the single chokepoint so new capture sources don't fan out type handling.

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
