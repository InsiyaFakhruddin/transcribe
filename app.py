# app.py
import streamlit as st
from pathlib import Path
import platform, shutil

# ---------- Safe defaults (UI only) ----------
DEFAULT_MODEL = "tiny.en"
DEFAULT_MIN_SPK = 2
DEFAULT_MAX_SPK = 6

# Try to import the pipeline & local recorder (optional)
start_recording = stop_recording = transcribe_and_diarize = save_outputs = None
try:
    from meeting_transcriber import (
        DEFAULT_MODEL as _DM, DEFAULT_MIN_SPK as _MIN, DEFAULT_MAX_SPK as _MAX,
        start_recording as _start, stop_recording as _stop,
        transcribe_and_diarize as _transcribe, save_outputs as _save
    )
    DEFAULT_MODEL, DEFAULT_MIN_SPK, DEFAULT_MAX_SPK = _DM, _MIN, _MAX
    start_recording, stop_recording = _start, _stop
    transcribe_and_diarize, save_outputs = _transcribe, _save
except Exception:
    # On Streamlit Cloud this is fine; browser capture tab doesn’t need the heavy deps
    pass

# Detect whether local recorder can work on this host
LOCAL_RECORDER_AVAILABLE = (
    platform.system() == "Linux"
    and shutil.which("pactl") is not None
    and shutil.which("ffmpeg") is not None
    and start_recording is not None
    and stop_recording is not None
)

# ---------- UI setup ----------
st.set_page_config(page_title="Meeting Transcriber", layout="centered")

OUTPUT_DIR = Path.home() / "MeetingTranscripts"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

st.title("Meeting Transcriber")

with st.sidebar:
    st.markdown("### Transcription Settings")
    model_choice = st.selectbox(
        "Whisper Model",
        ["tiny.en", "base.en", "small.en", "medium"],
        index=["tiny.en", "base.en", "small.en", "medium"].index(DEFAULT_MODEL)
        if DEFAULT_MODEL in ["tiny.en", "base.en", "small.en", "medium"] else 0,
    )
    min_speakers = st.number_input("Min Speakers", min_value=1, max_value=10, value=DEFAULT_MIN_SPK, step=1)
    max_speakers = st.number_input("Max Speakers", min_value=2, max_value=10, value=DEFAULT_MAX_SPK, step=1)
    if min_speakers > max_speakers:
        st.warning("Min speakers cannot be greater than Max speakers. Adjusted automatically.")
        min_speakers = max(1, min_speakers)
        max_speakers = max(min_speakers, max_speakers)

tab1, tab2 = st.tabs(["🔊 Capture ONE tab + Mic (Browser → Upload)", "💻 Local recorder (Linux/advanced)"])

# ---------- TAB 1: Browser capture ----------
with tab1:
    st.markdown(
        """
**How to use (Chrome/Edge desktop recommended):**
1. Click **Start** → in the picker select your **meeting tab** and tick **Share tab audio**.
2. Grant **microphone** permission.
3. Speak normally. When done click **Stop** → the browser uploads to your server.
4. Your server runs the same Python pipeline and saves **.md**, **.srt**, **.txt** (and a normalized **.wav**) in `~/MeetingTranscripts`.
        """
    )

    # Default the endpoint from secrets if provided, else localhost for dev
    endpoint_default = "https://transcribe-0kv2.onrender.com/upload"
    endpoint = st.text_input("Upload endpoint", value=endpoint_default, help="Your FastAPI /upload URL")

    st.components.v1.html(
        f"""
<div style="display:flex; gap:8px; align-items:center; margin: 8px 0 4px 0;">
  <button id="start" style="padding:8px 12px;">Start</button>
  <button id="stop" style="padding:8px 12px;" disabled>Stop</button>
</div>
<pre id="status" style="font-family:monospace; white-space:pre-wrap; background:#0f1117; color:#e6edf3; padding:10px; border-radius:6px; min-height:120px;"></pre>

<script>
const statusEl = document.getElementById('status');
let mediaRecorder;
let recordedChunks = [];
let mixedStream;
let ctx, dest, tabStream, micStream;

const MODEL = {repr(model_choice)};
const MIN_SPK = {int(min_speakers)};
const MAX_SPK = {int(max_speakers)};
const ENDPOINT = {repr(endpoint)};

function log(m) {{ statusEl.textContent += (statusEl.textContent ? "\\n" : "") + m; }}

async function wakeApi() {{
  try {{
    const base = ENDPOINT.replace(/\\/upload$/, "");
    await fetch(base + "/health", {{ method: "GET", cache: "no-store" }});
    log("API is awake.");
  }} catch (e) {{
    log("Could not wake API: " + e);
  }}
}}

async function startCapture() {{
  try {{
    await wakeApi();  // wake before recording/upload
    const tab = await navigator.mediaDevices.getDisplayMedia({{ video: true, audio: true }});
    const mic = await navigator.mediaDevices.getUserMedia({{ audio: true }});

    ctx = new (window.AudioContext || window.webkitAudioContext)();
    dest = ctx.createMediaStreamDestination();
    const tabSrc = ctx.createMediaStreamSource(tab);
    const micSrc = ctx.createMediaStreamSource(mic);

    const tabGain = ctx.createGain(); tabGain.gain.value = 1.0;
    const micGain = ctx.createGain(); micGain.gain.value = 1.0;
    tabSrc.connect(tabGain).connect(dest);
    micSrc.connect(micGain).connect(dest);

    recordedChunks = [];
    tabStream = tab; micStream = mic; mixedStream = dest.stream;

    // Lower bitrate for smaller, faster uploads (~48 kbps)
    const opts = {{ mimeType: 'audio/webm;codecs=opus', audioBitsPerSecond: 48000 }};
    mediaRecorder = new MediaRecorder(mixedStream, opts);
    mediaRecorder.ondataavailable = (e) => {{ if (e.data && e.data.size > 0) recordedChunks.push(e.data); }};
    mediaRecorder.onstop = onStop;

    mediaRecorder.start(1000); // gather chunks every second
    document.getElementById('start').disabled = true;
    document.getElementById('stop').disabled = false;

    statusEl.textContent = "";
    log("Recording… (selected tab + mic)");
    log("Tip: Keep the same tab focused to ensure tab audio stays shared.");
  }} catch (e) {{
    log("Failed to start capture: " + e);
  }}
}}

async function onStop() {{
  log("Finalizing recording…");
  try {{
    const blob = new Blob(recordedChunks, {{ type: 'audio/webm' }});
    const file = new File([blob], "browser_capture.webm", {{ type: 'audio/webm' }});

    const form = new FormData();
    form.append('file', file);
    form.append('model', MODEL);
    form.append('min_spk', String(MIN_SPK));
    form.append('max_spk', String(MAX_SPK));

    log("Uploading to: " + ENDPOINT);
    const resp = await fetch(ENDPOINT, {{ method: 'POST', body: form }});
    const data = await resp.json();
    if (data.ok) {{
      log("Server finished. Saved files (links):");
      log(JSON.stringify(data.saved, null, 2));
    }} else {{
      log("Server returned an error response.");
    }}
  }} catch (e) {{
    log("Upload failed: " + e);
  }} finally {{
    try {{ tabStream?.getTracks().forEach(t => t.stop()); micStream?.getTracks().forEach(t => t.stop()); }} catch (_e) {{}}
    document.getElementById('start').disabled = false;
    document.getElementById('stop').disabled = true;
  }}
}}

document.getElementById('start').onclick = startCapture;
document.getElementById('stop').onclick = () => {{
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {{
    mediaRecorder.stop();
    log("Stopping recorder…");
  }}
}};
</script>
        """,
        height=320,
    )

# ---------- TAB 2: Local recorder (optional) ----------
with tab2:
    st.markdown("""
**Optional local recording (Linux/PulseAudio/PipeWire)**  
This uses your existing `start_recording()` / `stop_recording()` that mix the default **monitor** + **mic** with FFmpeg.
""")

    if not LOCAL_RECORDER_AVAILABLE:
        st.info(
            "Local recorder isn’t available on this host. "
            "Run locally on **Linux** with PulseAudio/PipeWire and `pactl` + `ffmpeg` installed, "
            "or use the first tab (Browser capture) when deployed on Streamlit Cloud."
        )
    else:
        if "is_recording" not in st.session_state:
            st.session_state.is_recording = False
        if "recording_state" not in st.session_state:
            st.session_state.recording_state = None

        colA, colB = st.columns(2)
        with colA:
            if st.button("Start (local PulseAudio)"):
                if not st.session_state.is_recording:
                    try:
                        st.session_state.recording_state = start_recording()
                        st.session_state.is_recording = True
                        st.success(f"Recording → {st.session_state.recording_state.wav_path}")
                    except Exception as e:
                        st.error(f"Failed to start local recording: {e}")

        with colB:
            if st.button("Stop & Transcribe (local)"):
                if st.session_state.is_recording and st.session_state.recording_state:
                    try:
                        stop_recording(st.session_state.recording_state)
                        st.session_state.is_recording = False
                        wav_path = st.session_state.recording_state.wav_path
                        st.info("Transcribing + diarizing (CPU)…")
                        segs = transcribe_and_diarize(wav_path, model_choice, min_speakers, max_speakers)
                        md, srt, txt = save_outputs(wav_path, segs)
                        st.success(f"Saved:\n- {md}\n- {srt}\n- {txt}")
                    except Exception as e:
                        st.error(f"Local processing failed: {e}")
