"""Config flow for ESPHome Fleet (HI.1).

Two entry paths:
  - manual: user types the base URL of a running add-on
  - zeroconf: HA discovers the add-on's advertised `_esphome-fleet._tcp`
              service (HI.7) and offers a one-click confirm screen.

Both land in `_async_create_entry` which de-duplicates by URL.

Structure adapted from Ardumine's PR #57 with the post-rebrand domain
(`esphome_fleet`) and name ("ESPHome Fleet").
"""

from __future__ import annotations

from urllib.parse import urlparse

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import zeroconf
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from .const import CONF_BASE_URL, DEFAULT_TITLE, DOMAIN, ZEROCONF_TYPE


def _url_schema(default_url: str | None = None) -> vol.Schema:
    if default_url is None:
        return vol.Schema({vol.Required(CONF_BASE_URL): str})
    return vol.Schema({vol.Required(CONF_BASE_URL, default=default_url): str})


def _normalize_base_url(value: str) -> str:
    """Validate and normalize an http(s) base URL.

    Rejects anything that isn't a bare scheme+host(+port), since the
    integration appends its own `/ui/api/*` paths.
    """
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError
    return normalized


class EsphomeFleetConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ESPHome Fleet."""

    VERSION = 1

    _discovery_name: str | None = None
    _discovery_url: str | None = None

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Handle manual setup."""
        errors: dict[str, str] = {}

        if user_input is not None:
            candidate = user_input.get(CONF_BASE_URL, "")
            try:
                base_url = _normalize_base_url(candidate)
            except ValueError:
                errors["base"] = "invalid_url"
            else:
                return await self._async_create_entry(base_url)

        return self.async_show_form(
            step_id="user",
            data_schema=_url_schema(),
            errors=errors,
        )

    async def async_step_hassio(
        self, discovery_info: HassioServiceInfo
    ) -> FlowResult:
        """Handle Supervisor-initiated discovery (#26).

        When the add-on starts, it POSTs to `/discovery` on the
        Supervisor API with its internal hostname + port, which HA
        forwards here. Since the add-on is running locally and we
        already trust it (we wouldn't have been auto-installed
        otherwise), we skip the URL prompt entirely and create the
        config entry directly.
        """
        config = discovery_info.config or {}
        host = config.get("host")
        port = config.get("port")
        if not host or not port:
            return self.async_abort(reason="invalid_discovery_info")

        scheme = "https" if config.get("ssl") else "http"
        base_url = f"{scheme}://{host}:{port}"

        # De-dupe by URL — if the user already set this up manually,
        # don't create a second entry. Also prevents repeated discovery
        # flows from piling up.
        await self.async_set_unique_id(base_url.lower())
        self._abort_if_unique_id_configured()

        # Still route through the confirm screen so the user sees a
        # one-click notification rather than an unexplained entry
        # appearing — matches the pattern HA uses for other add-on
        # sidecar integrations.
        self._discovery_name = DEFAULT_TITLE
        self._discovery_url = base_url
        self.context["title_placeholders"] = {"name": DEFAULT_TITLE}
        return await self.async_step_discovery_confirm()

    async def async_step_zeroconf(
        self, discovery_info: zeroconf.ZeroconfServiceInfo
    ) -> FlowResult:
        """Handle zeroconf discovery."""
        if not discovery_info.host or not discovery_info.port:
            return await self.async_step_user()

        # `discovery_info.name` is the full mDNS service instance name,
        # e.g. "ESPHome Fleet._esphome-fleet._tcp.local.". Strip the
        # service-type suffix so the confirm dialog shows just the
        # human-readable instance label (#31).
        raw_name = (discovery_info.name or "").removesuffix(
            f".{ZEROCONF_TYPE}"
        ).removesuffix(ZEROCONF_TYPE)
        self._discovery_name = raw_name.strip(". ") or DEFAULT_TITLE
        self._discovery_url = f"http://{discovery_info.host}:{discovery_info.port}"
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Confirm setup for a discovered service."""
        if self._discovery_url is None:
            return await self.async_step_user()

        errors: dict[str, str] = {}

        if user_input is not None:
            candidate = user_input.get(CONF_BASE_URL, "")
            try:
                base_url = _normalize_base_url(candidate)
            except ValueError:
                errors["base"] = "invalid_url"
            else:
                return await self._async_create_entry(base_url)

        return self.async_show_form(
            step_id="discovery_confirm",
            data_schema=_url_schema(self._discovery_url),
            description_placeholders={
                "name": self._discovery_name or DEFAULT_TITLE,
                "url": self._discovery_url,
            },
            errors=errors,
        )

    async def _async_create_entry(self, base_url: str) -> FlowResult:
        """Create a config entry for the provided base URL."""
        await self.async_set_unique_id(base_url.lower())
        self._abort_if_unique_id_configured()
        title = self._discovery_name or DEFAULT_TITLE
        return self.async_create_entry(
            title=title,
            data={CONF_BASE_URL: base_url},
        )
