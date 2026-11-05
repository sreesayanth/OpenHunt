FROM python:3.12-slim

WORKDIR /app
ENV OPENHUNT_DATA=/data OPENHUNT_HOST=0.0.0.0 OPENHUNT_PORT=8080 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
COPY pyproject.toml README.md ./
COPY openhunt ./openhunt
# Chromium is included so applying works without any download at runtime.
RUN pip install --no-cache-dir ".[boards,apply]" \
    && python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

VOLUME /data
EXPOSE 8080
CMD ["openhunt"]
