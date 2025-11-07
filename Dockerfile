# Python 3.11 slim
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

# System deps for Playwright
RUN apt-get update && apt-get install -y \
    wget curl unzip libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libxkbcommon0 libxcomposite1 libxrandr2 libxdamage1 libgbm-dev \
    libpango-1.0-0 libasound2 libxshmfence1 libx11-xcb1 libgtk-3-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy & install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install --with-deps chromium

# Copy project files
COPY . .

EXPOSE 8000

# Run FastAPI app with dynamic PORT
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}"]
