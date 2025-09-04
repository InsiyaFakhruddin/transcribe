# Dockerfile
FROM python:3.11-slim

# System deps (ffmpeg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg git && rm -rf /var/lib/apt/lists/*

# Workdir & copy
WORKDIR /app
COPY requirements.txt /app/requirements.txt

# Faster installs
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest
COPY . /app

# Expose port for FastAPI
ENV PORT=7861
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7861"]
