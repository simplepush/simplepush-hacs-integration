"""The simplepush component."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import discovery
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_DELETE_AFTER,
    CONF_ENTRY_ID,
    CONF_TOPIC,
    CONF_TOPICS,
    DATA_HASS_CONFIG,
    DOMAIN,
)
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the simplepush component."""

    hass.data[DATA_HASS_CONFIG] = config
    hass.data.setdefault(DOMAIN, {})
    async_setup_services(hass)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate a config entry."""
    if entry.version == 1:
        # Version 1 entries hold a device key, password and salt from the old
        # Simplepush API. The current API authenticates with a user API token
        # and addresses topics, so there is nothing to carry over.
        _LOGGER.error(
            "The Simplepush entry %s was created for the old device-key API. "
            "Remove it and add Simplepush again with your API token",
            entry.title,
        )
        return False
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up simplepush from a config entry."""
    topics = {
        subentry.data[CONF_TOPIC]: subentry.data.get(CONF_PASSWORD)
        for subentry in entry.subentries.values()
    }

    hass.async_create_task(
        discovery.async_load_platform(
            hass,
            Platform.NOTIFY,
            DOMAIN,
            {
                **entry.data,
                CONF_TOPICS: topics,
                CONF_DELETE_AFTER: entry.options.get(CONF_DELETE_AFTER),
                CONF_ENTRY_ID: entry.entry_id,
            },
            hass.data[DATA_HASS_CONFIG],
        )
    )

    # Changed topics or options rebuild the client and restart its listeners.
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry after its topics changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if service := hass.data[DOMAIN].pop(entry.entry_id, None):
        await service.async_unregister_services()
        await service.async_close()
    return True
