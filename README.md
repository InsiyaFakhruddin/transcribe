cat > README.md << 'EOF'
# Meeting Transcriber (Tab + Mic → Upload)

Web UI (Streamlit) that captures **one browser tab + microphone** in the client, uploads to a FastAPI **/upload** endpoint, then runs the same Python pipeline (faster-whisper + ECAPA diarization) and saves `.md`, `.srt`, `.txt` in `~/MeetingTranscripts`.

## Local dev

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

# terminal A
python server.py        # → http://localhost:7861/upload

# terminal B
streamlit run app.py    # → http://localhost:8501
