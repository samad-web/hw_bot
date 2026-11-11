FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Kolkata

WORKDIR /app

# Install system dependencies for Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    curl \
    xvfb \
    xauth \
    libatomic1 \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps chromium

# Copy application source code
COPY config.py checker.py executor.py hardening.py logger.py notifier.py state.py main.py config.yaml ./

# Ensure volume directories exist
RUN mkdir -p /app/profile /app/logs /app/data

# State lives in a mounted DIRECTORY: state.json is rewritten with os.replace(),
# which fails with EBUSY against a bind-mounted single file.
# Virtual screen: the browser runs headful (BROWSER_HEADLESS=0) because Blinkit's
# checkout rejects headless browsers.
CMD ["xvfb-run", "-a", "python", "main.py", "--state", "/app/data/state.json"]
