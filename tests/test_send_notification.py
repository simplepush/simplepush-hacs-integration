"""Test the Simplepush send_notification action."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from simplepush import (
    Action,
    Event,
    NotificationActionInput,
    NotificationActionReply,
    NotificationChoiceInput,
    NotificationChoiceReply,
    NotificationCompleted,
    NotificationTextInput,
    NotificationTextReply,
)
import voluptuous as vol

from custom_components.simplepush_hacs.const import (
    CONF_TOPIC,
    DOMAIN,
    EVENT_NOTIFICATION_COMPLETED,
    SERVICE_SEND_NOTIFICATION,
    SUBENTRY_TOPIC,
)
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import CONF_API_TOKEN, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

ACTIONS = [{"action": "yes", "id": 123, "style": "primary"}, {"action": "no"}]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    yield


def _sent(*items, wait_forever: bool = False) -> MagicMock:
    async def inputs(**kwargs):
        for item in items:
            yield item
        if wait_forever:
            await asyncio.Event().wait()

    sent = MagicMock()
    sent.notification_id = "ntf_1"
    sent.inputs = inputs
    return sent


def _completed(reply) -> NotificationCompleted:
    return NotificationCompleted(
        notification_id="ntf_1",
        reply=reply,
        raw=Event(created_at="2026-09-27T10:00:00Z"),
    )


@pytest.fixture
async def client(hass: HomeAssistant):
    """Set up a Simplepush entry with a mocked client."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_TOKEN: "abc", CONF_NAME: "simplepush"},
        subentries_data=[
            ConfigSubentryData(
                data={CONF_TOPIC: "alerts"},
                subentry_type=SUBENTRY_TOPIC,
                title="alerts",
                unique_id="alerts",
            )
        ],
        unique_id="16a3ed4144494134",
        version=2,
    )
    entry.add_to_hass(hass)
    with patch("custom_components.simplepush_hacs.notify.create_client") as create:
        create.return_value.aclose = AsyncMock()
        assert await async_setup_component(hass, DOMAIN, {})
        await hass.async_block_till_done()
        client = create.return_value
        client.entry_id = entry.entry_id
        yield client


async def _send(hass: HomeAssistant, client, return_response: bool, **data):
    return await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_NOTIFICATION,
        {"config_entry_id": client.entry_id, "message": "hello", **data},
        blocking=True,
        return_response=return_response,
    )


async def test_send_without_response(hass: HomeAssistant, client) -> None:
    """The data is passed through and the action returns right away."""
    client.send_notification.return_value = _sent()

    await _send(
        hass,
        client,
        False,
        topic="alerts",
        title="Hi",
        priority=4,
        image="https://example.com/cam.jpg",
        link="https://example.com",
    )

    kwargs = client.send_notification.call_args.kwargs
    assert kwargs["topic"] == "alerts"
    assert kwargs["title"] == "Hi"
    assert kwargs["content"] == "hello"
    assert kwargs["priority"] == 4
    assert kwargs["image"] == "https://example.com/cam.jpg"
    assert kwargs["audio"] is None
    assert kwargs["link"] == "https://example.com"
    assert kwargs["input"] is None
    assert kwargs["shared"] is False


async def test_response_without_input_is_the_id(hass: HomeAssistant, client) -> None:
    """Without an input there is nothing to wait for."""
    client.send_notification.return_value = _sent()

    response = await _send(hass, client, True)

    assert response == {"notification_id": "ntf_1"}
    assert client.send_notification.call_args.kwargs["topic"] is None


async def test_text_answer(hass: HomeAssistant, client) -> None:
    """A text answer is returned and fires the event."""
    client.send_notification.return_value = _sent(
        _completed(NotificationTextReply(value="On my way"))
    )
    events = async_capture_events(hass, EVENT_NOTIFICATION_COMPLETED)

    response = await _send(hass, client, True, input={"type": "text"}, timeout=60)

    assert client.send_notification.call_args.kwargs["input"] == NotificationTextInput()
    assert response == {
        "notification_id": "ntf_1",
        "status": "completed",
        "completed_at": "2026-09-27T10:00:00Z",
        "text": "On my way",
    }
    await hass.async_block_till_done()
    assert [event.data for event in events] == [response]


async def test_choice_answer(hass: HomeAssistant, client) -> None:
    """The chosen option is returned."""
    client.send_notification.return_value = _sent(
        _completed(NotificationChoiceReply(selected_index=1, selected_value="Pasta"))
    )

    response = await _send(
        hass,
        client,
        True,
        input={"type": "choice", "options": ["Pizza", "Pasta"]},
        timeout=60,
    )

    assert client.send_notification.call_args.kwargs[
        "input"
    ] == NotificationChoiceInput(options=["Pizza", "Pasta"])
    assert response["choice"] == "Pasta"


async def test_action_answer(hass: HomeAssistant, client) -> None:
    """The selected action's text and id are returned."""
    client.send_notification.return_value = _sent(
        _completed(NotificationActionReply(selected_key="0"))
    )

    response = await _send(
        hass,
        client,
        True,
        input={"type": "actions", "actions": ACTIONS},
        timeout=60,
    )

    assert client.send_notification.call_args.kwargs[
        "input"
    ] == NotificationActionInput(
        actions=[
            Action(key="0", label="yes", style="primary"),
            Action(key="1", label="no", style=None),
        ]
    )
    assert response["action"] == "yes"
    assert response["action_id"] == 123


async def test_wait_ends_at_the_timeout(hass: HomeAssistant, client) -> None:
    """Without an answer in time the response says so."""
    client.send_notification.return_value = _sent(wait_forever=True)

    response = await _send(hass, client, True, input={"type": "text"}, timeout=0.01)

    assert response == {"notification_id": "ntf_1", "status": "pending"}


async def test_waiting_needs_timeout(hass: HomeAssistant, client) -> None:
    """Waiting for an answer without a timeout is refused before sending."""
    with pytest.raises(ServiceValidationError, match="timeout"):
        await _send(hass, client, True, input={"type": "text"})

    client.send_notification.assert_not_called()


@pytest.mark.parametrize(
    "data",
    [
        {"image": "https://example.com/a.jpg", "audio": "https://example.com/a.mp3"},
        {"link": "https://example.com", "input": {"type": "text"}},
        {"input": {"type": "photo"}},
        {"input": {"type": "choice", "options": ["A", "B", "C", "D"]}},
        {
            "input": {
                "type": "actions",
                "actions": [
                    {"action": "A"},
                    {"action": "B"},
                    {"action": "C"},
                    {"action": "D"},
                ],
            }
        },
    ],
)
async def test_invalid_combinations_are_refused(
    hass: HomeAssistant, client, data
) -> None:
    """Refuse image with audio, link with input, task-only inputs and over 3 buttons."""
    with pytest.raises(vol.Invalid):
        await _send(hass, client, False, **data)

    client.send_notification.assert_not_called()


async def test_local_media_outside_allowlist_is_refused(
    hass: HomeAssistant, client
) -> None:
    """A local image is checked like task files."""
    hass.config.allowlist_external_dirs = {"/config/www"}

    with pytest.raises(ServiceValidationError, match="/config/secrets.jpg"):
        await _send(hass, client, False, image="/config/secrets.jpg")

    client.send_notification.assert_not_called()


async def test_unknown_topic_is_refused(hass: HomeAssistant, client) -> None:
    """A topic that is not added to the entry is a validation error."""
    with pytest.raises(ServiceValidationError, match="Add the topic other"):
        await _send(hass, client, False, topic="other")

    client.send_notification.assert_not_called()
