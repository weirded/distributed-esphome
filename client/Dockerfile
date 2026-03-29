FROM python:3.11-slim
RUN apt-get update && apt-get install -y gcc libffi-dev libssl-dev git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py .
VOLUME /esphome-versions
# Store PlatformIO toolchains inside the persistent esphome-versions volume
# so they survive container recreations (avoid re-downloading toolchains each time).
ENV PLATFORMIO_CORE_DIR=/esphome-versions/platformio
ENTRYPOINT ["python", "client.py"]
