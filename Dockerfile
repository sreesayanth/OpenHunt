FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY openhunt ./openhunt
RUN pip install --no-cache-dir ".[boards]"

ENV OPENHUNT_DATA=/data OPENHUNT_HOST=0.0.0.0 OPENHUNT_PORT=8080
VOLUME /data
EXPOSE 8080
CMD ["openhunt"]
