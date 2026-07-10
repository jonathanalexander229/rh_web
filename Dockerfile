FROM python:3.13-slim

# Timezone data is used by pytz-driven market-hours logic
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=America/New_York

WORKDIR /app

# Install dependencies first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Runtime state (databases, logs, exports) and the Robinhood token dir
# are provided via volume mounts in docker-compose.yml.
EXPOSE 3000 5001

# Default command is overridden per-service in docker-compose.yml
CMD ["python", "-m", "portfolio.rh_web"]
