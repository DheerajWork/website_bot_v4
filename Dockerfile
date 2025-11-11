# ✅ Base image
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV OPENAI_API_KEY=${OPENAI_API_KEY}

# ✅ Install dependencies
RUN apt-get update && apt-get install -y \
    wget curl unzip libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libxkbcommon0 libxcomposite1 libxrandr2 libxdamage1 libgbm-dev \
    libpango-1.0-0 libasound2 libxshmfence1 libx11-xcb1 libgtk-3-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ✅ Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ✅ Install Playwright Chromium (headless)
RUN playwright install --with-deps chromium

# ✅ Copy project files
COPY . .

# ✅ Expose correct Railway port
EXPOSE ${PORT}

# ✅ Start FastAPI app with Railway PORT
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT} --timeout-keep-alive 75"]
