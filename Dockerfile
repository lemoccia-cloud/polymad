FROM python:3.11-slim

WORKDIR /app

# Install OS deps (curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY . .

# Make startup script executable
RUN chmod +x start.sh

# Streamlit public port (overridden by $PORT in Railway)
EXPOSE 8501
# FastAPI internal port (loopback only — not exposed via Railway)
EXPOSE 8000

# start-period increased to 30s to allow both FastAPI and Streamlit to warm up
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl --fail http://localhost:${PORT:-8501}/_stcore/health || exit 1

CMD ["./start.sh"]
