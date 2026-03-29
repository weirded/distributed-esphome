#!/usr/bin/with-contenv bashio

# Start the local build client unless disabled in add-on config.
if ! bashio::config.true 'disable_local_client'; then
  (
    sleep 5
    TOKEN=""
    for i in $(seq 1 10); do
      TOKEN=$(cat /data/auth_token 2>/dev/null || echo "")
      [ -n "$TOKEN" ] && break
      sleep 1
    done
    if [ -z "$TOKEN" ]; then
      bashio::log.warning "local-client: could not read auth token; skipping"
      exit 0
    fi
    ESPHOME_BIN=$(which esphome 2>/dev/null || echo "")
    if [ -z "$ESPHOME_BIN" ]; then
      bashio::log.warning "local-client: esphome binary not found; skipping"
      exit 0
    fi
    bashio::log.info "local-client: starting with esphome at ${ESPHOME_BIN}"
    exec env \
      SERVER_URL=http://localhost:8765 \
      SERVER_TOKEN="${TOKEN}" \
      ESPHOME_BIN="${ESPHOME_BIN}" \
      PLATFORMIO_CORE_DIR=/data/platformio \
      HOSTNAME="$(hostname)" \
      python3 /app/client/client.py
  ) &
fi

# Start the server as the main (foreground) process
exec python3 /app/main.py
