ARG BUILD_FROM
ARG BUILD_ARCH
ARG BUILD_VERSION

FROM $BUILD_FROM

LABEL \
    io.hass.name="ESPHome Distributed Build Server" \
    io.hass.description="Distributed ESPHome compilation coordinator" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version="${BUILD_VERSION}"

# Match ESPHome's docker-base environment for local worker PlatformIO compilation
ENV UV_EXTRA_INDEX_URL=https://wheels.home-assistant.io/musllinux-index/
ENV UV_SYSTEM_PYTHON=true
ENV UV_INDEX_STRATEGY=unsafe-best-match
ENV PIP_ROOT_USER_ACTION=ignore
RUN apk add --no-cache bash git curl openssh-client patch build-base libffi-dev openssl-dev gcompat
RUN pip3 install --no-cache-dir -U pip uv

WORKDIR /app
COPY server/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
COPY server/ .
COPY VERSION /app/VERSION

# Bundle client code and install its dependencies for the local worker
COPY client/ /app/client/
RUN pip3 install --no-cache-dir -r /app/client/requirements.txt

ENTRYPOINT []
CMD ["python3", "/app/main.py"]
