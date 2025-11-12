# ----------------------------
# Step 1: Base Image
# Using Python 3.11 slim version for a lightweight container
# ----------------------------
FROM python:3.11-slim

# ----------------------------
# Step 2: Set Environment Variables
# ----------------------------
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# ----------------------------
# Step 3: Install System Dependencies (for Playwright/Chromium)
# ----------------------------
RUN apt-get update && apt-get install -y \
    wget curl unzip libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libxkbcommon0 libxcomposite1 libxrandr2 libxdamage1 libgbm-dev \
    libpango-1.0-0 libasound2 libxshmfence1 libx11-xcb1 libgtk-3-0 \
    && rm -rf /var/lib/apt/lists/*

# ----------------------------
# Step 4: Set Working Directory
# ----------------------------
WORKDIR /app

# ----------------------------
# Step 5: Install Python Dependencies
# ----------------------------
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ----------------------------
# Step 6: Install Playwright & Chromium (headless)
# ----------------------------
RUN playwright install --with-deps chromium

# ----------------------------
# Step 7: Copy all project files
# ----------------------------
COPY . .

# ----------------------------
# Step 8: Expose port
# Railway provides dynamic $PORT, fallback 8000 for local testing
# ----------------------------
EXPOSE ${PORT:-8000}

# ----------------------------
# Step 9: Start FastAPI app (Railway-compatible)
# ----------------------------
# ✅ Important fix for 502: use ONLY $PORT assigned by Railway
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT} --timeout-keep-alive 75"]
