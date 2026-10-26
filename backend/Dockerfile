# ComplyPK backend image (Req 12.7).
# Minimal container that installs dependencies and serves the FastAPI app with
# uvicorn. No secrets are baked in; all configuration comes from environment
# variables injected by the host at runtime (Req 9.1).
FROM python:3.11-slim

# Keep Python output unbuffered and skip writing .pyc files in the container.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies first to leverage Docker layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source.
COPY app ./app

# Bind to all interfaces and use the platform-provided $PORT, defaulting to 8000
# when PORT is unset. Shell form is used so $PORT is expanded at runtime.
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
