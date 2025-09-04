# server.py
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from datetime import datetime
import subprocess
import os

from meeting_transcriber import (
    transcribe_and_diarize, save_outputs,
    DEFAULT_MODEL, DEFAULT_MIN_SPK, DEFAULT_MAX_SPK
)

UPLOAD_DIR = Path.home() / "MeetingTranscripts"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI()

# CORS: allow Streamlit UI on a different origin/port
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],    # tighten later if you want
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/upload")
async def upload_audio(
    file: UploadFile = File(...),
    model: str = Form(DEFAULT_MODEL),
    min_spk: int = Form(DEFAULT_MIN_SPK),
    max_spk: int = Form(DEFAULT_MAX_SPK)
):
    # Save with timestamped name to avoid collisions
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_suffix = Path(file.filename).suffix.lower()
    raw_path = UPLOAD_DIR / f"browser_{now}{raw_suffix if raw_suffix else '.webm'}"

    # Write upload to disk
    with open(raw_path, "wb") as f:
        f.write(await file.read())

    # Ensure mono 16k WAV for your pipeline
    wav_path = raw_path.with_suffix(".wav")
    if raw_path.suffix.lower() != ".wav":
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(raw_path),
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            str(wav_path),
        ]
        subprocess.run(cmd, check=True)
        src_for_asr = wav_path
    else:
        # If it already is wav, still normalize to mono16k
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(raw_path),
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            str(wav_path),
        ]
        subprocess.run(cmd, check=True)
        src_for_asr = wav_path

    # Run your existing pipeline
    segments = transcribe_and_diarize(src_for_asr, model, min_spk, max_spk)
    md, srt, txt = save_outputs(src_for_asr, segments)

    return JSONResponse({
        "ok": True,
        "saved": {"md": str(md), "srt": str(srt), "txt": str(txt)}
    })

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "7861"))
    uvicorn.run(app, host="0.0.0.0", port=port)
