# ✅ Use Python 3.11 slim base image
FROM python:3.11-slim

# ✅ Prevent interactive tzdata prompts
ENV DEBIAN_FRONTEND=noninteractive

# ✅ Install system dependencies required by Playwright
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    unzip \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxrandr2 \
    libxdamage1 \
    libgbm-dev \
    libpango-1.0-0 \
    libasound2 \
    libxshmfence1 \
    libx11-xcb1 \
    libgtk-3-0 \
    && rm -rf /var/lib/apt/lists/*

# ✅ Set working directory
WORKDIR /app

# ✅ Copy requirements first for caching
COPY requirements.txt .

# ✅ Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# ✅ Install Playwright browsers
RUN playwright install --with-deps chromium

# ✅ Copy all project files
COPY . .

# ✅ Expose the port for Railway
EXPOSE 8000

# ✅ Run the FastAPI app with uvicorn (dynamic port from Railway)
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}"]
