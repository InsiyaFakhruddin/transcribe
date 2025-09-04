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

# CORS (allow Streamlit UI on a different origin/port)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # tighten later (e.g., ["https://your-streamlit-app.streamlit.app"])
    allow_credentials=True,
    allow_methods=["*"],
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
