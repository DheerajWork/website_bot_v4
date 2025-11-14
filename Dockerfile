# Use Python 3.11 slim image
FROM python:3.11-slim

# ---------------- Install system dependencies for Playwright ----------------
RUN apt-get update && \
    apt-get install -y \
    wget curl unzip libnss3 libatk-bridge2.0-0 libxkbcommon0 libgtk-3-0 \
    libdrm2 libgbm1 libasound2 libxdamage1 libxfixes3 libxrandr2 \
    libpango-1.0-0 libcairo2 fonts-liberation libappindicator3-1 libxshmfence1 \
    git build-essential && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# ---------------- Set working directory ----------------
WORKDIR /app

# ---------------- Copy project files ----------------
COPY . /app

# ---------------- Upgrade pip and install Python dependencies ----------------
RUN python -m pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# ---------------- Install Playwright browsers ----------------
RUN python -m playwright install --with-deps chromium

# ---------------- Set environment variables ----------------
ENV PORT=8000
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# ---------------- Start server ----------------
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000} --timeout-keep-alive 75"]
