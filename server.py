# server.py
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from datetime import datetime
import subprocess
import os

from meeting_transcriber import (
    transcribe_and_diarize, save_outputs,
    DEFAULT_MODEL, DEFAULT_MIN_SPK, DEFAULT_MAX_SPK
)
# server.py (add import near the top)
from fastapi.responses import HTMLResponse

# ---------------------- Paths ----------------------
UPLOAD_DIR = Path.home() / "MeetingTranscripts"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------- App ------------------------
app = FastAPI()

@app.get("/health")
def health():
    return {"ok": True}

# Expose transcripts for direct download at /files/<filename>
app.mount("/files", StaticFiles(directory=str(UPLOAD_DIR)), name="files")

# server.py (add this route anywhere after app = FastAPI())
@app.get("/capture", response_class=HTMLResponse)
def capture_page():
    # A simple top-level recorder page hosted on Render
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Meeting Recorder</title>
  <style>
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif; max-width:900px; margin:24px auto; padding:0 12px;}
    button{padding:8px 12px; margin-right:8px}
    pre{background:#0f1117; color:#e6edf3; padding:12px; border-radius:8px; min-height:140px; white-space:pre-wrap}
  </style>
</head>
<body>
  <h2>Meeting Recorder (tab + mic → upload)</h2>
  <ol>
    <li>Click <b>Start</b> → select your <b>meeting tab</b> and tick <b>Share tab audio</b>.</li>
    <li>Grant <b>microphone</b> permission.</li>
    <li>Click <b>Stop</b> to upload and transcribe.</li>
  </ol>

  <div>
    <button id="start">Start</button>
    <button id="stop" disabled>Stop</button>
  </div>
  <pre id="status"></pre>

<script>
const statusEl = document.getElementById('status');
let mediaRecorder;
let recordedChunks = [];
let mixedStream;
let ctx, dest, tabStream, micStream;

// Read options from query string (?model=base.en&min=2&max=6)
const q = new URLSearchParams(location.search);
const MODEL   = q.get("model") || "tiny.en";
const MIN_SPK = parseInt(q.get("min") || "2");
const MAX_SPK = parseInt(q.get("max") || "6");
// Use same-origin /upload so no CORS
const ENDPOINT = window.location.origin + "/upload";

function log(m){ statusEl.textContent += (statusEl.textContent ? "\\n":"") + m; }

async function wakeApi(){
  try{
    await fetch(window.location.origin + "/health", {method:"GET", cache:"no-store"});
    log("API is awake.");
  }catch(e){ log("Could not wake API: " + e); }
}

async function startCapture(){
  try{
    await wakeApi();
    const tab = await navigator.mediaDevices.getDisplayMedia({video:true, audio:true});
    const mic = await navigator.mediaDevices.getUserMedia({audio:true});

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

    // Lower bitrate for faster uploads (~48 kbps)
    const opts = {{ mimeType: 'audio/webm;codecs=opus', audioBitsPerSecond: 48000 }};
    mediaRecorder = new MediaRecorder(mixedStream, opts);
    mediaRecorder.ondataavailable = (e)=>{{ if(e.data && e.data.size>0) recordedChunks.push(e.data); }};
    mediaRecorder.onstop = onStop;
    mediaRecorder.start(1000);

    document.getElementById('start').disabled = true;
    document.getElementById('stop').disabled = false;
    statusEl.textContent = "";
    log("Recording… (selected tab + mic)");
  }catch(e){
    log("Failed to start capture: " + e);
  }
}

async function onStop(){
  log("Finalizing recording…");
  try{
    const blob = new Blob(recordedChunks, {{type:'audio/webm'}});
    const file = new File([blob], "browser_capture.webm", {{type:'audio/webm'}});
    const form = new FormData();
    form.append('file', file);
    form.append('model', MODEL);
    form.append('min_spk', String(MIN_SPK));
    form.append('max_spk', String(MAX_SPK));

    log("Uploading to: " + ENDPOINT);
    const resp = await fetch(ENDPOINT, {{method:'POST', body: form}});
    const data = await resp.json();
    if (data.ok) {{
      log("Server finished. Saved files (links):");
      log(JSON.stringify(data.saved, null, 2));
    }} else {{
      log("Server error.");
    }}
  }catch(e){
    log("Upload failed: " + e);
  }finally{
    try{{ tabStream?.getTracks().forEach(t=>t.stop()); micStream?.getTracks().forEach(t=>t.stop()); }}catch(_){ }
    document.getElementById('start').disabled = false;
    document.getElementById('stop').disabled = true;
  }
}

document.getElementById('start').onclick = startCapture;
document.getElementById('stop').onclick  = ()=>{{ if(mediaRecorder && mediaRecorder.state!=='inactive'){{ mediaRecorder.stop(); log("Stopping recorder…"); }} }};
</script>
</body>
</html>
    """


# CORS (allow Streamlit UI on a different origin/port)
# server.py (replace the CORS block)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://meeting-transcriber.streamlit.app",  # your Streamlit URL
        "http://localhost:8501",                      # local dev
    ],
    allow_credentials=True,
    allow_methods=["POST", "OPTIONS", "GET"],
    allow_headers=["*"],
)


# ---------------------- Upload API -----------------
@app.post("/upload")
async def upload_audio(
    request: Request,
    file: UploadFile = File(...),
    model: str = Form(DEFAULT_MODEL),
    min_spk: int = Form(DEFAULT_MIN_SPK),
    max_spk: int = Form(DEFAULT_MAX_SPK),
):
    """Accepts a browser recording (webm/wav), converts to mono 16k wav,
    runs your pipeline, saves .md/.srt/.txt, and returns public URLs."""
    # Timestamped base name
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_suffix = Path(file.filename).suffix.lower() or ".webm"
    raw_path = UPLOAD_DIR / f"browser_{now}{raw_suffix}"

    # Save upload to disk
    with open(raw_path, "wb") as f:
        f.write(await file.read())

    # Normalize to mono 16k WAV for the pipeline
    wav_path = raw_path.with_suffix(".wav")
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(raw_path),
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(wav_path),
    ]
    subprocess.run(cmd, check=True)
    src_for_asr = wav_path

    # Run transcription + diarization
    segments = transcribe_and_diarize(src_for_asr, model, min_spk, max_spk)
    md, srt, txt = save_outputs(src_for_asr, segments)

    # Build public URLs (served by /files mount)
    base = str(request.base_url).rstrip("/")
    def to_url(p: Path) -> str:
        return f"{base}/files/{p.name}"

    return JSONResponse({
        "ok": True,
        "saved": {
            "md":  to_url(md),
            "srt": to_url(srt),
            "txt": to_url(txt),
        }
    })

# ---------------------- Main -----------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "7861"))
    uvicorn.run(app, host="0.0.0.0", port=port)
