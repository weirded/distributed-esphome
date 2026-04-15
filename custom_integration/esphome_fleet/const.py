"""Constants for the ESPHome Fleet integration."""

DOMAIN = "esphome_fleet"
DEFAULT_TITLE = "ESPHome Fleet"

CONF_BASE_URL = "base_url"
CONF_TOKEN = "token"

# Coordinator poll interval — matches the UI's 1Hz SWR polling for
# workers/devices/queue. 30s here is deliberately slower because HA
# entities don't need sub-second freshness.
DEFAULT_POLL_INTERVAL_SECONDS = 30

# mDNS service type advertised by the add-on (HI.7).
ZEROCONF_TYPE = "_esphome-fleet._tcp.local."
