"""Test the Simplepush send_task action."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from simplepush import (
    ActionUpload,
    DownloadError,
    Event,
    PhotoInput,
    PhotoUpload,
    TaskCompleted,
    TaskExpired,
    TextInput,
    TextUpload,
)
import voluptuous as vol

from custom_components.simplepush_hacs.const import (
    CONF_TOPIC,
    DOMAIN,
    EVENT_ACTION_TRIGGERED,
    EVENT_TASK_COMPLETED,
    SERVICE_SEND_TASK,
    SUBENTRY_TOPIC,
)
from custom_components.simplepush_hacs.notify import _extension
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
ACTIONS_INPUT = {"type": "actions", "actions": ACTIONS}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    yield


def _stream(*items):
    async def inputs(**kwargs):
        for item in items:
            yield item

    return inputs


def _sent(*items) -> MagicMock:
    sent = MagicMock()
    sent.task_id = "tsk_1"
    sent.inputs = _stream(*items)
    return sent


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
        SERVICE_SEND_TASK,
        {"config_entry_id": client.entry_id, "message": "hello", **data},
        blocking=True,
        return_response=return_response,
    )


async def test_send_without_response(hass: HomeAssistant, client) -> None:
    """The data is passed through and the action returns right away."""
    client.send_task.return_value = _sent()
    hass.config.allowlist_external_dirs = {"/config/www"}

    await _send(
        hass,
        client,
        False,
        topic="alerts",
        title="Hi",
        priority=4,
        expires_in=60,
        files="/config/www/a.jpg",
        links=["https://example.com"],
        inputs=[ACTIONS_INPUT],
    )

    kwargs = client.send_task.call_args.kwargs
    assert kwargs["topic"] == "alerts"
    assert kwargs["title"] == "Hi"
    assert kwargs["content"] == "hello"
    assert kwargs["priority"] == 4
    assert kwargs["files"] == ["/config/www/a.jpg"]
    assert kwargs["links"] == ["https://example.com"]
    assert kwargs["auto_commit"] is True
    assert kwargs["expires_at"] is not None


async def test_response_without_inputs_is_the_task_id(
    hass: HomeAssistant, client
) -> None:
    """Without inputs there is nothing to wait for."""
    client.send_task.return_value = _sent()

    response = await _send(hass, client, True)

    assert response == {"task_id": "tsk_1"}
    assert client.send_task.call_args.kwargs["topic"] is None
    assert client.send_task.call_args.kwargs["title"] == "Home Assistant"


async def test_response_waits_for_the_answer(hass: HomeAssistant, client) -> None:
    """The response is the first answer, and the action event still fires."""
    client.send_task.return_value = _sent(
        TaskCompleted(
            task_id="tsk_1",
            uploads=[ActionUpload(id="inp_1", key="0")],
            raw=Event(created_at="2026-09-27T10:00:00Z"),
        )
    )
    events = async_capture_events(hass, EVENT_ACTION_TRIGGERED)

    response = await _send(hass, client, True, expires_in=60, inputs=[ACTIONS_INPUT])

    assert response == {
        "task_id": "tsk_1",
        "status": "completed",
        "completed_at": "2026-09-27T10:00:00Z",
        "action": "yes",
        "action_id": 123,
    }
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["id"] == 123


async def test_response_reports_expiry(hass: HomeAssistant, client) -> None:
    """A task that expires unanswered ends the wait with its status."""
    client.send_task.return_value = _sent(
        TaskExpired(task_id="tsk_1", created_at=None, raw=Event())
    )

    response = await _send(hass, client, True, expires_in=60, inputs=[ACTIONS_INPUT])

    assert response == {"task_id": "tsk_1", "status": "expired"}


async def test_waiting_needs_expires_in(hass: HomeAssistant, client) -> None:
    """Waiting for an answer without a deadline is refused before sending."""
    with pytest.raises(ServiceValidationError, match="expires_in"):
        await _send(hass, client, True, inputs=[ACTIONS_INPUT])

    client.send_task.assert_not_called()


async def test_invalid_priority_is_refused(hass: HomeAssistant, client) -> None:
    """The schema refuses a priority outside 1 to 5."""
    with pytest.raises(vol.Invalid):
        await _send(hass, client, False, priority=6)

    client.send_task.assert_not_called()


async def test_unknown_topic_is_refused(hass: HomeAssistant, client) -> None:
    """A topic that is not added to the entry is a validation error."""
    with pytest.raises(ServiceValidationError, match="Add the topic other"):
        await _send(hass, client, False, topic="other")

    client.send_task.assert_not_called()


async def test_unknown_entry_is_refused(hass: HomeAssistant, client) -> None:
    """An entry that is not set up is a validation error."""
    with pytest.raises(ServiceValidationError, match="not set up"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SEND_TASK,
            {"config_entry_id": "missing", "message": "hello"},
            blocking=True,
        )


async def test_text_input_answer(hass: HomeAssistant, client) -> None:
    """A text input is required on its own and its answer is returned."""
    client.send_task.return_value = _sent(
        TaskCompleted(
            task_id="tsk_1",
            uploads=[TextUpload(id="inp_1", value="Moving furniture")],
            raw=Event(created_at="2026-09-27T10:00:00Z"),
        )
    )
    events = async_capture_events(hass, EVENT_TASK_COMPLETED)

    response = await _send(
        hass,
        client,
        True,
        expires_in=60,
        inputs=[{"type": "text", "description": "Why?", "default_value": "Because"}],
    )

    assert client.send_task.call_args.kwargs["inputs"] == [
        TextInput(description="Why?", default_value="Because", required=True)
    ]
    assert response == {
        "task_id": "tsk_1",
        "status": "completed",
        "completed_at": "2026-09-27T10:00:00Z",
        "text": "Moving furniture",
    }
    await hass.async_block_till_done()
    assert [event.data for event in events] == [response]


async def test_optional_text_next_to_actions(hass: HomeAssistant, client) -> None:
    """A text with required: false is an optional note to the selected action."""
    client.send_task.return_value = _sent(
        TaskCompleted(
            task_id="tsk_1",
            uploads=[
                ActionUpload(id="inp_1", key="1"),
                TextUpload(id="inp_2", value="Guests are still here"),
            ],
            raw=Event(created_at="2026-09-27T10:00:00Z"),
        )
    )

    response = await _send(
        hass,
        client,
        True,
        expires_in=60,
        inputs=[ACTIONS_INPUT, {"type": "text", "required": False}],
    )

    _, text_input = client.send_task.call_args.kwargs["inputs"]
    assert text_input == TextInput(required=False)
    assert response["action"] == "no"
    assert response["text"] == "Guests are still here"


def _photo(read: AsyncMock) -> MagicMock:
    photo = MagicMock(spec=PhotoUpload)
    photo.id = "inp_1"
    photo.filename = None
    photo.content_type = "image/jpeg"
    photo.read = read
    return photo


async def test_photo_input_is_saved_to_media(
    hass: HomeAssistant, client, tmp_path
) -> None:
    """A photo answer is saved to the local media folder."""
    hass.config.media_dirs = {"local": str(tmp_path)}
    client.send_task.return_value = _sent(
        TaskCompleted(
            task_id="tsk_1",
            uploads=[_photo(AsyncMock(return_value=b"jpeg bytes"))],
            raw=Event(created_at="2026-09-27T10:00:00Z"),
        )
    )

    response = await _send(
        hass, client, True, expires_in=60, inputs=[{"type": "photo"}]
    )

    assert client.send_task.call_args.kwargs["inputs"] == [PhotoInput(required=True)]
    path = tmp_path / "simplepush" / "tasks" / "inp_1.jpg"
    assert path.read_bytes() == b"jpeg bytes"
    assert response["photo"] == str(path)
    assert (
        response["photo_media_content_id"]
        == "media-source://media_source/local/simplepush/tasks/inp_1.jpg"
    )


async def test_failed_photo_download_still_answers(
    hass: HomeAssistant, client, tmp_path, caplog
) -> None:
    """A photo that cannot be downloaded is logged and left out of the answer."""
    hass.config.media_dirs = {"local": str(tmp_path)}
    client.send_task.return_value = _sent(
        TaskCompleted(
            task_id="tsk_1",
            uploads=[_photo(AsyncMock(side_effect=DownloadError("no key")))],
            raw=Event(created_at="2026-09-27T10:00:00Z"),
        )
    )

    response = await _send(
        hass, client, True, expires_in=60, inputs=[{"type": "photo"}]
    )

    assert response["status"] == "completed"
    assert "photo" not in response
    assert "Failed to download the photo of task tsk_1: no key" in caplog.text


async def test_shared_markdown_task_names_who_answered(
    hass: HomeAssistant, client
) -> None:
    """A shared task is one task, and its answer names who gave it."""
    client.send_task.return_value = _sent(
        TaskCompleted(
            task_id="tsk_1",
            uploads=[ActionUpload(id="inp_1", key="0")],
            raw=Event(
                created_at="2026-09-27T10:00:00Z",
                actor={"publicId": "usr_1", "name": "Alice"},
            ),
        )
    )

    response = await _send(
        hass,
        client,
        True,
        shared=True,
        markdown=True,
        expires_in=60,
        inputs=[ACTIONS_INPUT],
    )

    kwargs = client.send_task.call_args.kwargs
    assert kwargs["shared"] is True
    assert kwargs["content_format"] == "markdown"
    assert response["recipient"] == "Alice"
    assert response["recipient_id"] == "usr_1"


async def test_actions_are_required_by_default(hass: HomeAssistant, client) -> None:
    """An input is required unless it says required: false."""
    client.send_task.return_value = _sent()

    await _send(hass, client, False, inputs=[ACTIONS_INPUT])

    (action_input,) = client.send_task.call_args.kwargs["inputs"]
    assert action_input.required is True


async def test_all_optional_inputs_are_allowed(hass: HomeAssistant, client) -> None:
    """With no required input the first answer completes the task."""
    client.send_task.return_value = _sent()

    await _send(hass, client, False, inputs=[{**ACTIONS_INPUT, "required": False}])

    (action_input,) = client.send_task.call_args.kwargs["inputs"]
    assert action_input.required is False


async def test_input_type_used_twice_is_refused(hass: HomeAssistant, client) -> None:
    """Each input type can only be used once in a task."""
    with pytest.raises(ServiceValidationError, match="only be used once"):
        await _send(hass, client, False, inputs=[ACTIONS_INPUT, ACTIONS_INPUT])

    client.send_task.assert_not_called()


@pytest.mark.parametrize(
    ("content_type", "filename", "extension"),
    [
        ("image/jpeg", None, ".jpg"),
        ("image/png", "IMG_1.jpg", ".png"),
        ("audio/m4a", None, ".m4a"),
        ("application/pdf", None, ".pdf"),
        ("application/octet-stream", "invoice.pdf", ".pdf"),
        ("application/x-unknown", None, ""),
        ("application/octet-stream", None, ""),
    ],
)
def test_extension_comes_from_content_type(content_type, filename, extension) -> None:
    """The content type decides the extension, the file name only for octet-stream."""
    assert _extension(content_type, filename) == extension
