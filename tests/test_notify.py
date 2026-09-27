"""Test the Simplepush notify service."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from simplepush import (
    ActionsInput,
    ActionUpload,
    ApiError,
    Event,
    GroupInput,
    InputEvent,
    TaskCompleted,
    TaskGroup,
    TaskGroupRecipient,
    TextUpload,
)

from custom_components.simplepush_hacs.const import (
    CONF_ENTRY_ID,
    CONF_TOPICS,
    DOMAIN,
    EVENT_ACTION_TRIGGERED,
)
from custom_components.simplepush_hacs.notify import SimplePushNotificationService
from homeassistant.const import CONF_API_TOKEN, CONF_NAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import async_capture_events

CONFIG = {
    CONF_API_TOKEN: "abc",
    CONF_NAME: "simplepush",
    CONF_PASSWORD: "personal",
    CONF_TOPICS: {"alerts": "hunter2", "open": None},
    CONF_ENTRY_ID: "entry",
}


def _completed(*uploads) -> TaskCompleted:
    return TaskCompleted(
        task_id="tsk_1", uploads=list(uploads), raw=Event(created_at="2026-09-14T10:00:00Z")
    )


def _stream(*items):
    async def inputs(**kwargs):
        inputs.kwargs = kwargs
        for item in items:
            yield item

    return inputs


@pytest.fixture
def client():
    """Mock the Simplepush client."""
    with patch("custom_components.simplepush_hacs.notify.create_client") as mock:
        yield mock.return_value


@pytest.fixture
def service(hass: HomeAssistant, client) -> SimplePushNotificationService:
    """Build the notify service under test."""
    hass.data[DOMAIN] = {}
    return SimplePushNotificationService(hass, CONFIG)


async def test_plain_message(hass: HomeAssistant, client, service) -> None:
    """A message without data is sent as a task to your own devices."""
    await service.async_send_message("hello", title="Hi")
    await hass.async_block_till_done()

    kwargs = client.send_task.call_args.kwargs
    assert kwargs["topic"] is None
    assert "password" not in kwargs
    assert kwargs["title"] == "Hi"
    assert kwargs["content"] == "hello"
    assert kwargs["inputs"] is None
    assert kwargs["links"] is None
    assert kwargs["files"] is None
    assert kwargs["priority"] is None
    assert kwargs["expires_at"] is None
    assert kwargs["auto_commit"] is True


async def test_data_fields(hass: HomeAssistant, client, service) -> None:
    """Links, files, topic and priority are passed through."""
    hass.config.allowlist_external_dirs = {"/config/www"}
    await service.async_send_message(
        "hello",
        data={
            "links": "https://example.com",
            "files": ["/config/www/a.jpg", "/config/www/b.pdf"],
            "topic": "alerts",
            "priority": "5",
        },
    )
    await hass.async_block_till_done()

    kwargs = client.send_task.call_args.kwargs
    assert kwargs["topic"] == "alerts"
    assert kwargs["links"] == ["https://example.com"]
    assert kwargs["files"] == ["/config/www/a.jpg", "/config/www/b.pdf"]
    assert kwargs["priority"] == 5


async def test_client_holds_every_password(hass: HomeAssistant) -> None:
    """The client gets the personal password and each topic's password."""
    with patch("custom_components.simplepush_hacs.notify.create_client") as create:
        SimplePushNotificationService(hass, CONFIG)

    create.assert_called_once_with(
        "abc", "personal", {"alerts": "hunter2", "open": None}
    )


async def test_unknown_topic_is_not_sent(
    hass: HomeAssistant, client, service, caplog
) -> None:
    """A topic that is not added to the entry is refused."""
    await service.async_send_message("hello", data={"topic": "other"})
    await hass.async_block_till_done()

    client.send_task.assert_not_called()
    assert "Add the topic other to the Simplepush entry" in caplog.text


async def test_actions_fire_event(hass: HomeAssistant, client, service) -> None:
    """A selected action fires the Home Assistant event with label and id."""
    sent = MagicMock()
    sent.inputs = _stream(
        InputEvent(type="taskInputUploaded", uploads=[ActionUpload(id="inp_1", key="0")], raw=Event()),
        _completed(ActionUpload(id="inp_1", key="0")),
    )
    client.send_task.return_value = sent
    events = async_capture_events(hass, EVENT_ACTION_TRIGGERED)

    before = datetime.now(UTC)
    await service.async_send_message(
        "approve?",
        data={
            "expires_in": 10,
            "actions": [
                {"action": "yes", "id": 123, "style": "primary"},
                {"action": "no"},
            ],
        },
    )
    await hass.async_block_till_done()

    kwargs = client.send_task.call_args.kwargs
    (action_input,) = kwargs["inputs"]
    assert isinstance(action_input, ActionsInput)
    assert [(a.key, a.label, a.style) for a in action_input.actions] == [
        ("0", "yes", "primary"),
        ("1", "no", None),
    ]
    assert 9 <= (kwargs["expires_at"] - before).total_seconds() <= 11
    assert sent.inputs.kwargs == {}

    assert len(events) == 1
    assert events[0].data == {
        "action_selected": "yes",
        "action_selected_at": "2026-09-14T10:00:00Z",
        "task_id": "tsk_1",
        "id": 123,
    }


async def test_actions_without_expires_in_do_not_expire(
    hass: HomeAssistant, client, service
) -> None:
    """Without expires_in the task stays open in the app."""
    sent = MagicMock()
    sent.inputs = _stream()
    client.send_task.return_value = sent

    await service.async_send_message("approve?", data={"actions": [{"action": "yes"}]})
    await hass.async_block_till_done()

    assert client.send_task.call_args.kwargs["expires_at"] is None


async def test_group_actions_carry_recipient(hass: HomeAssistant, client, service) -> None:
    """Answers from a topic group name the recipient."""
    instance = MagicMock()
    instance.recipient = TaskGroupRecipient(public_id="usr_1", name="Alice")
    sent = MagicMock(spec=TaskGroup)
    sent.inputs = _stream(
        GroupInput(instance=instance, item=_completed(ActionUpload(id="inp_1", key="1")))
    )
    client.send_task.return_value = sent
    events = async_capture_events(hass, EVENT_ACTION_TRIGGERED)

    await service.async_send_message(
        "approve?", data={"actions": [{"action": "yes"}, {"action": "no"}]}
    )
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["action_selected"] == "no"
    assert "id" not in events[0].data
    assert events[0].data["recipient"] == "Alice"
    assert events[0].data["recipient_id"] == "usr_1"


async def test_non_action_upload_is_ignored(hass: HomeAssistant, client, service) -> None:
    """Uploads that are not action uploads fire no event."""
    sent = MagicMock()
    sent.inputs = _stream(
        _completed(TextUpload(id="inp_1", value="x"), ActionUpload(id="inp_2", key=None))
    )
    client.send_task.return_value = sent
    events = async_capture_events(hass, EVENT_ACTION_TRIGGERED)

    await service.async_send_message("approve?", data={"actions": [{"action": "yes"}]})
    await hass.async_block_till_done()

    assert events == []


async def test_url_actions_are_rejected(hass: HomeAssistant, client, service) -> None:
    """The old url actions are refused instead of sent without their url."""
    await service.async_send_message(
        "open", data={"actions": [{"action": "open", "url": "https://example.com"}]}
    )
    await hass.async_block_till_done()

    client.send_task.assert_not_called()


async def test_api_error_is_logged(hass: HomeAssistant, client, service, caplog) -> None:
    """A rejected send is logged and does not raise."""
    client.send_task.side_effect = ApiError(400, '{"error":"bad_request"}')

    await service.async_send_message("hello")
    await hass.async_block_till_done()

    assert "Simplepush rejected the task" in caplog.text


async def test_invalid_priority_is_not_sent(
    hass: HomeAssistant, client, service, caplog
) -> None:
    """A priority outside 1 to 5 is logged and nothing is sent."""
    for value in ("high", 0, 6):
        await service.async_send_message("hello", data={"priority": value})
    await hass.async_block_till_done()

    client.send_task.assert_not_called()
    assert "Priority must be a number from 1 to 5" in caplog.text


async def test_expires_in_without_actions(hass: HomeAssistant, client, service) -> None:
    """expires_in sets a deadline on a task without actions too."""
    before = datetime.now(UTC)
    await service.async_send_message("hello", data={"expires_in": "60"})
    await hass.async_block_till_done()

    expires_at = client.send_task.call_args.kwargs["expires_at"]
    assert 59 <= (expires_at - before).total_seconds() <= 61


async def test_invalid_expires_in_is_not_sent(
    hass: HomeAssistant, client, service, caplog
) -> None:
    """An expires_in that is not a positive number is logged and nothing is sent."""
    for value in ("soon", 0, -5):
        await service.async_send_message("hello", data={"expires_in": value})
    await hass.async_block_till_done()

    client.send_task.assert_not_called()
    assert "expires_in must be a positive number of seconds" in caplog.text


async def test_action_timeout_is_ignored_with_warning(
    hass: HomeAssistant, client, service, caplog
) -> None:
    """The 1.x action_timeout field is ignored and logged."""
    await service.async_send_message("hello", data={"action_timeout": 10})
    await hass.async_block_till_done()

    assert client.send_task.call_args.kwargs["expires_at"] is None
    assert "The action_timeout field is no longer supported" in caplog.text


async def test_files_outside_allowlist_are_not_sent(
    hass: HomeAssistant, client, service, caplog
) -> None:
    """A file outside allowlist_external_dirs stops the send."""
    hass.config.allowlist_external_dirs = {"/config/www"}
    await service.async_send_message(
        "hello",
        data={"files": ["/config/www/a.jpg", "/config/secrets.yaml"]},
    )
    await hass.async_block_till_done()

    client.send_task.assert_not_called()
    assert "not sent: /config/secrets.yaml" in caplog.text
