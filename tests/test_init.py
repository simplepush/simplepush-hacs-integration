"""Test Simplepush setup and unload."""

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.simplepush_hacs.const import CONF_TOPIC, DOMAIN, SUBENTRY_TOPIC
from homeassistant.config_entries import ConfigEntryState, ConfigSubentry
from homeassistant.const import CONF_API_TOKEN, CONF_NAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from pytest_homeassistant_custom_component.common import MockConfigEntry


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    yield


async def test_setup_and_unload_entry(hass: HomeAssistant) -> None:
    """The entry registers a notify service and closes the client on unload."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_TOKEN: "abc", CONF_NAME: "simplepush"},
        unique_id="16a3ed4144494134",
        version=2,
    )
    entry.add_to_hass(hass)

    with patch("custom_components.simplepush_hacs.notify.create_client") as create:
        create.return_value.aclose = AsyncMock()
        assert await async_setup_component(hass, DOMAIN, {})
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.LOADED
        assert hass.services.has_service("notify", "simplepush")
        assert entry.entry_id in hass.data[DOMAIN]

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert not hass.services.has_service("notify", "simplepush")
    assert entry.entry_id not in hass.data[DOMAIN]
    create.return_value.aclose.assert_awaited_once()


async def test_version_1_entry_is_not_migrated(hass: HomeAssistant) -> None:
    """Entries from the device-key API fail migration."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"device_key": "abc", CONF_NAME: "simplepush"},
        unique_id="abc",
        version=1,
    )
    entry.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.MIGRATION_ERROR


async def test_adding_a_topic_reloads_the_client(hass: HomeAssistant) -> None:
    """A new topic's password reaches the client after the entry reloads."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_TOKEN: "abc", CONF_NAME: "simplepush"},
        unique_id="16a3ed4144494134",
        version=2,
    )
    entry.add_to_hass(hass)

    with patch("custom_components.simplepush_hacs.notify.create_client") as create:
        create.return_value.aclose = AsyncMock()
        assert await async_setup_component(hass, DOMAIN, {})
        await hass.async_block_till_done()
        create.assert_called_once_with("abc", None, {})

        hass.config_entries.async_add_subentry(
            entry,
            ConfigSubentry(
                data={CONF_TOPIC: "alerts", CONF_PASSWORD: "hunter2"},
                subentry_type=SUBENTRY_TOPIC,
                title="alerts",
                unique_id="alerts",
            ),
        )
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert create.call_args.args == ("abc", None, {"alerts": "hunter2"})
    assert hass.services.has_service("notify", "simplepush")
