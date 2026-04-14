"""Config flow for Distributed ESPHome."""

from __future__ import annotations

from urllib.parse import urlparse

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import zeroconf
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_BASE_URL, DEFAULT_TITLE, DOMAIN


def _url_schema(default_url: str | None = None) -> vol.Schema:
    """Create the schema for entering the base URL."""
    if default_url is None:
        return vol.Schema({vol.Required(CONF_BASE_URL): str})
    return vol.Schema({vol.Required(CONF_BASE_URL, default=default_url): str})


def _normalize_base_url(value: str) -> str:
    """Validate and normalize a base URL."""
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


class DistributedESPHomeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Distributed ESPHome."""

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

    async def async_step_zeroconf(
        self, discovery_info: zeroconf.ZeroconfServiceInfo
    ) -> FlowResult:
        """Handle zeroconf discovery."""
        if not discovery_info.host or not discovery_info.port:
            return await self.async_step_user()

        self._discovery_name = discovery_info.name or DEFAULT_TITLE
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