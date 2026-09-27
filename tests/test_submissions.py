"""Test Simplepush submissions and the cleanup of downloaded files."""

import asyncio
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from simplepush import (
    ApiError,
    Event,
    Location,
    StreamError,
    Submission,
    SubmissionFile,
    TextBody,
)

from custom_components.simplepush_hacs.const import (
    CONF_DELETE_AFTER,
    DOMAIN,
    EVENT_SUBMISSION_RECEIVED,
)
from custom_components.simplepush_hacs.notify import _delete_old_files
from homeassistant.const import CONF_API_TOKEN, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    yield


def _submission(**parts) -> Submission:
    fields = {
        "body": None,
        "photo": None,
        "file": None,
        "audio": None,
        "location": None,
        **parts,
    }
    return Submission(
        id="sbm_1",
        created_at="2026-09-27T10:00:00Z",
        raw=Event(actor={"publicId": "usr_1", "name": "Alex"}),
        **fields,
    )


def _file(file_id: str, content_type: str, filename: str | None) -> MagicMock:
    upload = MagicMock(spec=SubmissionFile)
    upload.id = file_id
    upload.filename = filename
    upload.content_type = content_type
    upload.read = AsyncMock(return_value=b"bytes of " + file_id.encode())
    return upload


async def _wait_until(condition) -> None:
    """Wait for background work that runs in the executor."""
    for _ in range(200):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached")


async def _setup(
    hass: HomeAssistant, *submissions, options=None, submissions_mock=None
) -> MockConfigEntry:
    """Set up an entry whose client delivers `submissions`."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_TOKEN: "abc", CONF_NAME: "simplepush"},
        options=options or {},
        unique_id="16a3ed4144494134",
        version=2,
    )
    entry.add_to_hass(hass)

    async def stream():
        for submission in submissions:
            yield submission
        await asyncio.Event().wait()

    with patch("custom_components.simplepush_hacs.notify.create_client") as create:
        create.return_value.aclose = AsyncMock()
        create.return_value.submissions = submissions_mock or MagicMock(
            side_effect=stream
        )
        assert await async_setup_component(hass, DOMAIN, {})
        await hass.async_block_till_done()
    return entry


async def test_text_and_location_submission(hass: HomeAssistant) -> None:
    """A submission fires an event with its text, location and sender."""
    events = async_capture_events(hass, EVENT_SUBMISSION_RECEIVED)

    await _setup(
        hass,
        _submission(
            body=TextBody(text="Parked here"),
            location=Location(latitude=52.5, longitude=13.4, accuracy=8.0),
        ),
    )

    assert [event.data for event in events] == [
        {
            "submission_id": "sbm_1",
            "submitted_at": "2026-09-27T10:00:00Z",
            "sender": "Alex",
            "sender_id": "usr_1",
            "text": "Parked here",
            "latitude": 52.5,
            "longitude": 13.4,
            "accuracy": 8.0,
        }
    ]


async def test_submission_files_are_saved_to_media(
    hass: HomeAssistant, tmp_path
) -> None:
    """Photo and file of a submission land in the local media folder."""
    hass.config.media_dirs = {"local": str(tmp_path)}
    events = async_capture_events(hass, EVENT_SUBMISSION_RECEIVED)

    await _setup(
        hass,
        _submission(
            photo=_file("sbf_1", "image/jpeg", None),
            file=_file("sbf_2", "application/pdf", "invoice.pdf"),
        ),
    )
    await _wait_until(lambda: events)

    folder = tmp_path / "simplepush" / "submissions"
    (event,) = events
    assert event.data["photo"] == str(folder / "sbf_1.jpg")
    assert event.data["file"] == str(folder / "sbf_2.pdf")
    assert (folder / "sbf_1.jpg").read_bytes() == b"bytes of sbf_1"
    assert event.data["photo_media_content_id"] == (
        "media-source://media_source/local/simplepush/submissions/sbf_1.jpg"
    )
    assert "audio" not in event.data


def test_delete_old_files(tmp_path) -> None:
    """Old files and the folders they leave empty are deleted, new ones stay."""
    old = tmp_path / "tsk_1" / "inp_1.jpg"
    new = tmp_path / "submissions" / "sbm_1" / "sbf_1.jpg"
    for path in (old, new):
        path.parent.mkdir(parents=True)
        path.write_bytes(b"x")
    two_hours_ago = time.time() - 7200
    os.utime(old, (two_hours_ago, two_hours_ago))

    _delete_old_files(tmp_path, 3600)

    assert not old.exists()
    assert not old.parent.exists()
    assert new.exists()
    assert tmp_path.exists()


async def test_cleanup_runs_at_setup(hass: HomeAssistant, tmp_path) -> None:
    """With the setting, old downloads are deleted when the entry starts."""
    hass.config.media_dirs = {"local": str(tmp_path)}
    old = tmp_path / "simplepush" / "tsk_1" / "inp_1.jpg"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"x")
    two_days_ago = time.time() - 2 * 86400
    os.utime(old, (two_days_ago, two_days_ago))
    elsewhere = tmp_path / "holiday.jpg"
    elsewhere.write_bytes(b"x")
    os.utime(elsewhere, (two_days_ago, two_days_ago))

    await _setup(hass, options={CONF_DELETE_AFTER: 24})
    await _wait_until(lambda: not old.exists())

    assert elsewhere.exists()


async def test_downloads_are_kept_without_setting(
    hass: HomeAssistant, tmp_path
) -> None:
    """Without the setting nothing is deleted."""
    hass.config.media_dirs = {"local": str(tmp_path)}
    old = tmp_path / "simplepush" / "tsk_1" / "inp_1.jpg"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"x")
    os.utime(old, (0, 0))

    await _setup(hass)

    assert old.exists()


async def test_options_flow_sets_delete_after(hass: HomeAssistant) -> None:
    """The settings of an entry hold how long downloads are kept."""
    entry = await _setup(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    with patch("custom_components.simplepush_hacs.notify.create_client") as create:
        create.return_value.aclose = AsyncMock()
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={CONF_DELETE_AFTER: 48}
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_DELETE_AFTER: 48}


async def test_failed_stream_stops_listening(hass: HomeAssistant, caplog) -> None:
    """A failure the client can't recover from ends the listener with an error."""

    async def failing():
        raise StreamError("event stream rejected by server (HTTP 401)")
        yield

    submissions = MagicMock(side_effect=failing)
    await _setup(hass, submissions_mock=submissions)
    await _wait_until(lambda: "Stopped listening for submissions" in caplog.text)

    submissions.assert_called_once()


async def test_rejected_token_does_not_retry(hass: HomeAssistant, caplog) -> None:
    """A 4xx while starting the stream is logged once and not retried."""
    submissions = MagicMock(side_effect=ApiError(401, "unauthorized"))
    await _setup(hass, submissions_mock=submissions)
    await _wait_until(lambda: "Can't listen for submissions" in caplog.text)

    submissions.assert_called_once()
    assert "retrying" not in caplog.text
