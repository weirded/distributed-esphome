FROM python:3.11-slim

ARG BUILD_ARCH
ARG BUILD_VERSION

LABEL \
    io.hass.name="ESPHome Distributed Build Server" \
    io.hass.description="Distributed ESPHome compilation coordinator" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version="${BUILD_VERSION}"

# Same deps as the proven client Dockerfile — native glibc for PlatformIO toolchains
RUN apt-get update && apt-get install -y gcc libffi-dev libssl-dev git && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server/ .
COPY VERSION /app/VERSION

# Bundle client code and install its dependencies for the local worker
COPY client/ /app/client/
RUN pip install --no-cache-dir -r /app/client/requirements.txt

ENTRYPOINT []
CMD ["python3", "/app/main.py"]
