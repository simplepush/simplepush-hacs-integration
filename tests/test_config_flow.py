"""Test Simplepush config flow."""

import hashlib
from unittest.mock import patch

import pytest
from simplepush import ApiError

from custom_components.simplepush_hacs.const import CONF_TOPIC, DOMAIN, SUBENTRY_TOPIC
from homeassistant import config_entries
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import CONF_API_TOKEN, CONF_NAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from pytest_homeassistant_custom_component.common import MockConfigEntry

MOCK_CONFIG = {
    CONF_API_TOKEN: "abc",
    CONF_NAME: "simplepush",
}
UNIQUE_ID = hashlib.sha256(b"abc").hexdigest()[:16]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    yield


@pytest.fixture(autouse=True)
def simplepush_setup_fixture():
    """Patch simplepush setup entry."""
    with patch(
        "custom_components.simplepush_hacs.async_setup_entry", return_value=True
    ):
        yield


@pytest.fixture(autouse=True)
def create_client():
    """Patch the simplepush client used by the config flow."""
    with patch("custom_components.simplepush_hacs.config_flow.create_client") as mock:
        yield mock


def _entry(hass: HomeAssistant, *subentries: ConfigSubentryData) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG,
        subentries_data=list(subentries),
        unique_id=UNIQUE_ID,
        version=2,
    )
    entry.add_to_hass(hass)
    return entry


async def _user_flow(hass: HomeAssistant, user_input: dict):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    return await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=user_input,
    )


async def _topic_flow(hass: HomeAssistant, entry: MockConfigEntry, user_input: dict):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TOPIC),
        context={"source": config_entries.SOURCE_USER},
    )
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], user_input=user_input
    )


async def test_flow_successful(hass: HomeAssistant, create_client) -> None:
    """Test user initialized flow with minimum config."""
    result = await _user_flow(hass, MOCK_CONFIG)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "simplepush"
    assert result["data"] == MOCK_CONFIG
    assert result["result"].unique_id == UNIQUE_ID
    create_client.assert_called_once_with("abc", None)
    assert create_client.return_value.send_task.call_args.kwargs["topic"] is None


async def test_flow_with_personal_password(hass: HomeAssistant, create_client) -> None:
    """The personal password encrypts the test task to your own devices."""
    mock_config = {**MOCK_CONFIG, CONF_PASSWORD: "personal"}
    result = await _user_flow(hass, mock_config)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == mock_config
    create_client.assert_called_once_with("abc", "personal")


async def test_flow_user_token_already_configured(hass: HomeAssistant) -> None:
    """Test user initialized flow with a duplicate token."""
    _entry(hass)

    result = await _user_flow(hass, MOCK_CONFIG)

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_flow_user_name_already_configured(hass: HomeAssistant) -> None:
    """Test user initialized flow with duplicate name."""
    _entry(hass)

    result = await _user_flow(hass, {**MOCK_CONFIG, CONF_API_TOKEN: "abc1"})

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ApiError(401, '{"error":"unauthorized"}'), "invalid_auth"),
        (ApiError(500, "boom"), "cannot_connect"),
        (OSError("connection refused"), "cannot_connect"),
    ],
)
async def test_error_on_failure(
    hass: HomeAssistant, create_client, error, expected
) -> None:
    """Test the errors shown when the test task fails."""
    create_client.return_value.send_task.side_effect = error

    result = await _user_flow(hass, MOCK_CONFIG)

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def test_add_topic(hass: HomeAssistant, create_client) -> None:
    """A topic is added with its password after a test task to it."""
    entry = _entry(hass)

    result = await _topic_flow(
        hass, entry, {CONF_TOPIC: "alerts", CONF_PASSWORD: "hunter2"}
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    (subentry,) = entry.subentries.values()
    assert subentry.title == "alerts"
    assert subentry.unique_id == "alerts"
    assert subentry.data == {CONF_TOPIC: "alerts", CONF_PASSWORD: "hunter2"}
    create_client.assert_called_once_with("abc", topics={"alerts": "hunter2"})
    assert create_client.return_value.send_task.call_args.kwargs["topic"] == "alerts"


async def test_add_topic_twice(hass: HomeAssistant, create_client) -> None:
    """A topic can only be added once."""
    entry = _entry(
        hass,
        ConfigSubentryData(
            data={CONF_TOPIC: "alerts"},
            subentry_type=SUBENTRY_TOPIC,
            title="alerts",
            unique_id="alerts",
        ),
    )

    result = await _topic_flow(hass, entry, {CONF_TOPIC: "alerts"})

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    create_client.return_value.send_task.assert_not_called()


async def test_add_unknown_topic(hass: HomeAssistant, create_client) -> None:
    """A topic you have not joined shows an error."""
    create_client.return_value.send_task.side_effect = ApiError(
        403, '{"error":"not_topic_holder"}'
    )
    entry = _entry(hass)

    result = await _topic_flow(hass, entry, {CONF_TOPIC: "alerts"})

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "unknown_topic"}
    assert not entry.subentries


async def test_change_topic_password(hass: HomeAssistant, create_client) -> None:
    """The password of a topic can be changed."""
    entry = _entry(
        hass,
        ConfigSubentryData(
            data={CONF_TOPIC: "alerts", CONF_PASSWORD: "old"},
            subentry_type=SUBENTRY_TOPIC,
            title="alerts",
            unique_id="alerts",
        ),
    )
    (subentry,) = entry.subentries.values()

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TOPIC),
        context={"source": "reconfigure", "subentry_id": subentry.subentry_id},
    )
    assert result["description_placeholders"] == {"topic": "alerts"}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], user_input={CONF_PASSWORD: "new"}
    )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries[subentry.subentry_id].data == {
        CONF_TOPIC: "alerts",
        CONF_PASSWORD: "new",
    }
    create_client.assert_called_once_with("abc", topics={"alerts": "new"})
