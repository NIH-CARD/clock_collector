# Clock Drawing Screening — ALPHA (testing only)

A prototype that analyzes a hand-drawn analog clock with **Claude Opus 4.8
(vision)** using established Clock Drawing Test (CDT) scoring.

> 🚧 **ALPHA. Testing only. Use synthetic / fake data.**
> 🗄️ **This app stores nothing.** It shows the result JSON, then deletes it.
> 🩺 **Not a medical device. Not a diagnosis.**

> 📄 Released to the public domain under [CC0 1.0](LICENSE).

## What it does

A tester enters synthetic age + cognitive status, confirms the current time,
draws a circular analog clock set to that time, and photographs it. The image
goes to Claude Opus 4.8, which scores it against:

- **MoCA clock item** (0–3: contour / numbers / hands)
- **Shulman 5-point** and **Sunderland 10-point** scales
- **Rouleau-style qualitative error analysis** (visuospatial/executive,
  conceptual deficit, perseveration, graphic difficulty, stimulus-bound, planning)
- domain observations + cautious literature-association notes
- a target-vs-drawn **time-accuracy** check — the time is entered on a 12-hour
  picker (hour / minute / AM·PM) that defaults to the **user's local time**
  (from the browser timezone, not the server's), and the prompt reads the hands
  by **length** (hour = the shorter hand, minute = the longer hand)

A **Start over** button appears with the result; it clears all inputs and the
captured photo (the capture widgets re-mount empty) and returns to the
acknowledgement gate.

The drawing and result JSON are named `<ip>__<date>.png` / `.json` (the client
IP plus a UTC date-time), shown on screen with their contents, then the
temporary files are **deleted immediately**. Nothing is persisted: the IP and
date are used only to build those filenames and appear in the displayed output.
The IP comes from `st.context.ip_address`, or a reverse-proxy `X-Forwarded-For`
/ `X-Real-Ip` header; a localhost run is recorded as `127.0.0.1` (Streamlit
reports no IP for loopback clients).

## No storage — how it works

The app writes the drawing and the result JSON to temp files (named from IP +
date) purely so it can display real filenames and contents, then calls
`os.remove` on both and confirms they're gone (`transient_output.py`). There is
no database, no CSV, no retained images. A tester can optionally click the
"Download to your device" buttons — that's the tester saving locally, not the
app retaining anything.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...      # or paste it in the sidebar
streamlit run app.py
```

`app.py` resolves the key in this order: `st.secrets["ANTHROPIC_API_KEY"]` →
`ANTHROPIC_API_KEY` env var → a key typed into the sidebar. If a key is found in
secrets (or the environment), the app uses it and shows which source it came
from; otherwise the sidebar prompts for one (entered keys are not stored). The
model is pinned to `claude-opus-4-8`.

### Deploying from GitHub (Streamlit Community Cloud)

The repo never contains a real key. To run the deployed app without anyone
having to paste a key into the sidebar, set the key as a **Streamlit secret**:

- **Streamlit Community Cloud:** in the app's **Settings → Secrets**, add
  ```toml
  ANTHROPIC_API_KEY = "sk-ant-..."
  ```
  Streamlit stores it server-side and exposes it via `st.secrets` — it is
  **not** committed to GitHub.
- **Local equivalent:** copy `.streamlit/secrets.toml.example` to
  `.streamlit/secrets.toml` (gitignored) and fill in the key.

⚠️ **Never commit a real key.** A key pushed to GitHub is exposed even if later
deleted (it stays in history) and can be abused to run up API charges. Rotate
any key that has been committed.

## Camera capture (needs HTTPS or localhost)

Capture uses `st.camera_input` (live preview + click-to-capture) with
`st.file_uploader` as the alternative. Browsers only allow camera access in a
**secure context** — HTTPS, or a `localhost` origin — so:

- `http://localhost:8501` on the dev machine → camera works.
- `http://<lan-ip>:8501` from your phone over plain HTTP → camera is **blocked**
  by the browser (not a bug).
- Any HTTPS deployment → camera works on desktop and mobile, including iOS Safari.

**Detection is optimistic.** The only thing that switches the app to an
**upload-only** path is an *insecure context* — caught server-side by
`camera_can_work(st.context.url)` (plain HTTP to a remote host) or by the
client probe returning `"insecure"`. The app does **not** hide the camera just
because `navigator.mediaDevices.enumerateDevices()` reports no video device:
that call returns no `videoinput` *before the user grants camera permission* on
many browsers (notably iOS Safari), so trusting it would wrongly hide a working
camera over the web. The **Upload** tab is always available as a fallback, so a
device with genuinely no camera loses nothing. If `streamlit-javascript` isn't
installed, the app still runs on the server-side check alone.

To test the camera on a phone during development, use an HTTPS URL — deploy to
an HTTPS host, or tunnel (`cloudflared tunnel --url http://localhost:8501` /
`ngrok http 8501`) and open the `https://…` link on the phone. Running in WSL
and opening `http://localhost:8501` in the Windows browser counts as localhost,
so the camera works there.

Note: capture defaults to the **rear camera** on phones via
`streamlit-back-camera-input` (the camera points at the drawing, not the user's
face — better for privacy). If that package isn't installed, it falls back to
`st.camera_input` (browser's default camera). All capture sources — the
back-camera widget (base64 data URL), `st.camera_input`/`st.file_uploader`
(UploadedFile), or raw bytes — are normalized to `(bytes, mime)` by
`normalize_image()` before analysis.

## Files

| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI: acknowledgement gate, capture, print-then-delete result |
| `clock_analyzer.py` | Claude Opus 4.8 vision call + CDT prompt + JSON parsing |
| `scoring_utils.py` | Pure helpers (e.g. time-accuracy check); unit-tested |
| `transient_output.py` | Names files from IP + date, writes temp files, then deletes them |
| `test_basic.py` | pytest suite for the pure logic (no Streamlit/SDK/network) |
| `logos/` | Header branding shown at the top of the app (DataTecnica, Center for Alzheimer's, VCU) |

## Development (Claude Code)

See `CLAUDE.md` for project context and the hard invariants (no storage, not a
diagnosis, synthetic data only, IP+date filenames, pinned model). Quick loop:

```bash
pip install -r requirements-dev.txt
pytest -q          # pure logic only — no API key or network needed
```

Tests live in `test_basic.py` at the repo root and import the top-level modules
directly (no `tests/` package or `pyproject.toml` needed). The Anthropic SDK is
imported lazily inside `analyze_clock`, so the modules and tests import cleanly
without it.

## When you move past the prototype

This alpha deliberately punts on storage and compliance. Before collecting
**any real data**, whoever deploys this must handle: a real private store
(managed DB + private bucket, not the local filesystem), encryption at rest,
consent, a privacy policy, retention/deletion, and — given the health-adjacent
nature of the data — HIPAA / GDPR and likely IRB review. Keep the output framed
as screening, never diagnostic, to avoid turning it into a regulated medical
device.

## References

The scoring and interpretation in `clock_analyzer.py` are based on these
published Clock Drawing Test frameworks. Links were checked at the time of
writing.

- **MoCA (clock item, 0–3).** Nasreddine ZS, et al. The Montreal Cognitive
  Assessment, MoCA: A Brief Screening Tool for Mild Cognitive Impairment.
  *J Am Geriatr Soc.* 2005;53(4):695–699.
  https://doi.org/10.1111/j.1532-5415.2005.53221.x
- **Shulman 5-point scale (origin).** Shulman KI, Shedletsky R, Silver IL. The
  challenge of time: clock-drawing and cognitive function in the elderly.
  *Int J Geriatr Psychiatry.* 1986;1(2):135–140. This paper introduced the
  five-point hierarchical error-classification scale.
  https://doi.org/10.1002/gps.930010209
- **Shulman scale (later review).** Shulman KI. Clock-drawing: is it the
  ideal cognitive screening test? *Int J Geriatr Psychiatry.*
  2000;15(6):548–561. https://pubmed.ncbi.nlm.nih.gov/10861923/
- **Sunderland 10-point scale.** Sunderland T, et al. Clock drawing in
  Alzheimer's disease: a novel measure of dementia severity.
  *J Am Geriatr Soc.* 1989;37(8):725–729.
  https://pubmed.ncbi.nlm.nih.gov/2754157/
- **Rouleau qualitative error taxonomy.** Rouleau I, Salmon DP, Butters N,
  Kennedy C, McGuire K. Quantitative and qualitative analyses of clock drawings
  in Alzheimer's and Huntington's disease. *Brain Cogn.* 1992;18(1):70–87.
  https://doi.org/10.1016/0278-2626(92)90112-Y
- **General review (utility, scoring methods, caveats).** Pinto E, Peters R.
  Literature review of the Clock Drawing Test as a tool for cognitive
  screening. *Dement Geriatr Cogn Disord.* 2009;27(3):201–213.
  https://pubmed.ncbi.nlm.nih.gov/19225234/

**Important:** these are the frameworks the prompt draws on — they do not make
this app a validated instrument. CDT performance is influenced by vision, motor
control, education, language, and the drawing medium, and the literature notes
limited sensitivity for *mild* impairment. Subtype "association" notes (e.g.
conceptual/stimulus-bound errors discussed more in Alzheimer's contexts vs.
visuospatial/graphomotor errors in subcortical/vascular/Parkinsonian contexts)
are general tendencies from the literature, **not** a means of identifying any
condition in an individual.
