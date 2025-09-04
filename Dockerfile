# Dockerfile
FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg git && rm -rf /var/lib/apt/lists/*

# Env: keep caches under /root/.cache (default)
ENV HF_HOME=/root/.cache \
    TORCH_HOME=/root/.cache \
    SPEECHBRAIN_CACHE=/root/.cache \
    OMP_NUM_THREADS=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir -r requirements.txt

# copy code and warm up models into image layers (faster cold starts)
COPY . /app
RUN python warmup_models.py

# Run FastAPI
ENV PORT=7861
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7861"]
