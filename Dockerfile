# StudyBuddy Multi-Stage Docker Build
# Supports: MCP Server, Wellness Agent, API, Dashboard, and Offline Audio/TTS

FROM python:3.12-slim as base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies including audio/TTS libraries (espeak-ng, portaudio, ffmpeg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libssl-dev \
    espeak-ng \
    libportaudio2 \
    portaudio19-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY dashboard/ ./dashboard/
COPY .env.example ./.env
RUN mkdir -p /app/data /app/logs

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000 8001 8002 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["python", "-m", "src.server"]

FROM base as production
ENV APP_ENV=production
COPY --from=base /app /app
USER appuser
WORKDIR /app
CMD ["python", "-m", "src.server"]
