"""Simplepush notification service."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from functools import partial
import logging
import mimetypes
from pathlib import Path
import time
from typing import Any

from simplepush import (
    Action,
    ActionsInput,
    ActionUpload,
    ApiError,
    ChoiceInput,
    ChoiceUpload,
    ContentFormat,
    DownloadError,
    FileUpload,
    FileUploadInput,
    GroupInput,
    GroupNotification,
    LocationInput,
    LocationUpload,
    MultiChoiceUpload,
    NotificationActionInput,
    NotificationActionReply,
    NotificationChoiceInput,
    NotificationChoiceReply,
    NotificationCompleted,
    NotificationGroup,
    NotificationInput,
    NotificationTextInput,
    NotificationTextReply,
    PhotoInput,
    PhotoUpload,
    SliderInput,
    SliderUpload,
    StreamError,
    Submission,
    TaskCanceled,
    TaskCompleted,
    TaskDeclined,
    TaskDeleted,
    TaskExpired,
    TaskGroup,
    TextInput,
    TextUpload,
    VoiceRecordingInput,
    VoiceUpload,
)
import voluptuous as vol

from homeassistant.components.notify import (
    ATTR_DATA,
    ATTR_TITLE,
    ATTR_TITLE_DEFAULT,
    BaseNotificationService,
)
from homeassistant.const import CONF_API_TOKEN, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .client import create_client
from .const import (
    ATTR_EXPIRES_IN,
    ATTR_FILES,
    ATTR_INPUTS,
    ATTR_LINKS,
    ATTR_MARKDOWN,
    ATTR_PRIORITY,
    ATTR_SHARED,
    ATTR_TOPIC,
    CONF_DELETE_AFTER,
    CONF_ENTRY_ID,
    CONF_TOPICS,
    DOMAIN,
    EVENT_ACTION_TRIGGERED,
    EVENT_NOTIFICATION_COMPLETED,
    EVENT_SUBMISSION_RECEIVED,
    EVENT_TASK_COMPLETED,
)
from .services import NOTIFY_DATA_SCHEMA

_LOGGER = logging.getLogger(__name__)

# Service data keys of the old device-key API that no longer exist.
_REMOVED_DATA_KEYS = ("action_timeout", "actions", "attachments", "event")

# Wait before trying again to start listening for submissions.
_SUBMISSIONS_RETRY_SECONDS = 30

# Ends of a task without an answer, by the status reported for them.
_TERMINAL_STATUS: dict[type, str] = {
    TaskCanceled: "canceled",
    TaskDeclined: "declined",
    TaskDeleted: "deleted",
    TaskExpired: "expired",
}


async def async_get_service(
    hass: HomeAssistant,
    config: ConfigType,
    discovery_info: DiscoveryInfoType | None = None,
) -> SimplePushNotificationService | None:
    """Get the Simplepush notification service."""
    if discovery_info is None:
        async_create_issue(
            hass,
            DOMAIN,
            "removed_yaml",
            breaks_in_ha_version="2022.9.0",
            is_fixable=False,
            severity=IssueSeverity.WARNING,
            translation_key="removed_yaml",
        )
        return None

    service = SimplePushNotificationService(hass, discovery_info)
    hass.data[DOMAIN][discovery_info[CONF_ENTRY_ID]] = service
    service.async_start()
    return service


def _build_actions(
    actions: list[dict[str, Any]],
) -> tuple[ActionsInput, dict[str, tuple[str, Any]]]:
    """Turn validated `actions` data into a task input.

    Returns the input and a map from the generated action key to the action's
    label and optional id, used to build the answer and the Home Assistant event.
    """
    buttons: list[Action] = []
    lookup: dict[str, tuple[str, Any]] = {}
    for index, entry in enumerate(actions):
        key = str(index)
        buttons.append(Action(key=key, label=entry["action"], style=entry.get("style")))
        lookup[key] = (entry["action"], entry.get("id"))

    return ActionsInput(actions=buttons), lookup


def _build_inputs(
    inputs: list[dict[str, Any]],
) -> tuple[list[Any], dict[str, tuple[str, Any]]]:
    """Turn the `inputs` data into task inputs, in the given order.

    Returns the inputs and the action lookup of `_build_actions`.
    """
    types = [entry["type"] for entry in inputs]
    if len(set(types)) != len(types):
        raise ServiceValidationError("Each input type can only be used once")

    task_inputs: list[Any] = []
    action_lookup: dict[str, tuple[str, Any]] = {}
    for entry in inputs:
        description = entry.get("description")
        required = entry.get("required", True)
        match entry["type"]:
            case "actions":
                action_input, action_lookup = _build_actions(entry["actions"])
                action_input.description = description
                action_input.required = required
                task_inputs.append(action_input)
            case "text":
                task_inputs.append(
                    TextInput(
                        description=description,
                        default_value=entry.get("default_value"),
                        required=required,
                    )
                )
            case "photo":
                task_inputs.append(
                    PhotoInput(description=description, required=required)
                )
            case "choice":
                task_inputs.append(
                    ChoiceInput(
                        options=entry["options"],
                        description=description,
                        required=required,
                        multi=entry.get("multi", False),
                        min_selections=entry.get("min_selections"),
                        max_selections=entry.get("max_selections"),
                    )
                )
            case "slider":
                task_inputs.append(
                    SliderInput(
                        min=entry["min"],
                        max=entry["max"],
                        step=entry.get("step"),
                        unit=entry.get("unit"),
                        default_value=entry.get("default_value"),
                        description=description,
                        required=required,
                    )
                )
            case "voice":
                task_inputs.append(
                    VoiceRecordingInput(description=description, required=required)
                )
            case "location":
                task_inputs.append(
                    LocationInput(description=description, required=required)
                )
            case "file":
                task_inputs.append(
                    FileUploadInput(description=description, required=required)
                )
    return task_inputs, action_lookup


def _build_notification_input(
    entry: dict[str, Any],
) -> tuple[NotificationInput, dict[str, tuple[str, Any]]]:
    """Turn validated `input` data into a notification input and its action lookup."""
    match entry["type"]:
        case "text":
            return NotificationTextInput(), {}
        case "choice":
            return NotificationChoiceInput(options=entry["options"]), {}
        case "actions":
            action_input, action_lookup = _build_actions(entry["actions"])
            return NotificationActionInput(actions=action_input.actions), action_lookup
    raise ValueError(f"Unknown notification input type {entry['type']}")


def _delete_old_files(folder: Path, max_age: float) -> None:
    """Delete files in `folder` older than `max_age` seconds, then empty folders."""
    if not folder.is_dir():
        return
    cutoff = time.time() - max_age
    # Deepest paths first, so a folder is empty once its old files are gone.
    for path in sorted(folder.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        try:
            if path.is_file():
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            elif not any(path.iterdir()):
                path.rmdir()
        except OSError as err:
            _LOGGER.warning("Failed to delete %s: %s", path, err)


# Content types the app sends that Python's mimetypes does not know.
_EXTENSIONS = {"audio/m4a": ".m4a", "audio/x-m4a": ".m4a"}


def _extension(content_type: str, filename: str | None) -> str:
    """File extension of a download, from its content type.

    A file the phone couldn't identify (application/octet-stream) keeps the
    extension of its name.
    """
    if content_type == "application/octet-stream":
        return Path(filename).suffix if filename else ""
    return (
        _EXTENSIONS.get(content_type) or mimetypes.guess_extension(content_type) or ""
    )


class SimplePushNotificationService(BaseNotificationService):
    """Implementation of the notification service for Simplepush."""

    def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
        """Initialize the Simplepush notification service."""
        self.hass = hass
        self._entry_id: str = config[CONF_ENTRY_ID]
        self.topics: dict[str, str | None] = config[CONF_TOPICS]
        self._client = create_client(
            config[CONF_API_TOKEN], config.get(CONF_PASSWORD), self.topics
        )
        # Hours to keep downloaded files, or None to keep them.
        self._delete_after: float | None = config.get(CONF_DELETE_AFTER)
        self._submissions_task: asyncio.Task[None] | None = None
        self._stop_cleanup: Any = None

    @callback
    def async_start(self) -> None:
        """Listen for submissions and delete old downloads."""
        self._submissions_task = self.hass.async_create_background_task(
            self._listen_submissions(), name="simplepush submissions"
        )
        if self._delete_after is not None:
            self.hass.async_create_background_task(
                self._async_delete_old_files(), name="simplepush cleanup"
            )
            self._stop_cleanup = async_track_time_interval(
                self.hass, self._async_delete_old_files, timedelta(hours=1)
            )

    async def async_close(self) -> None:
        """Stop the listeners and close the client's event connection."""
        if self._submissions_task is not None:
            self._submissions_task.cancel()
        if self._stop_cleanup is not None:
            self._stop_cleanup()
        await self._client.aclose()

    @callback
    def _start_reauth(self) -> None:
        """Ask for a new API token.

        Callers start it on a 401: the token is gone, e.g. replaced in the app
        or rotated by erasing the account data. Home Assistant runs one reauth
        at a time.
        """
        if (
            entry := self.hass.config_entries.async_get_entry(self._entry_id)
        ) is not None:
            entry.async_start_reauth(self.hass)

    async def async_send_message(self, message: str, **kwargs: Any) -> None:
        """Send a task to a Simplepush user."""
        data: dict[str, Any] = dict(kwargs.get(ATTR_DATA) or {})
        for key in _REMOVED_DATA_KEYS:
            if key in data:
                del data[key]
                _LOGGER.warning(
                    "The %s field is no longer supported and was ignored", key
                )

        try:
            options = NOTIFY_DATA_SCHEMA(data)
        except vol.Invalid as err:
            _LOGGER.error("Invalid Simplepush data: %s", err)
            return

        try:
            await self.async_send_task(
                message=message,
                title=kwargs.get(ATTR_TITLE, ATTR_TITLE_DEFAULT),
                topic=options.get(ATTR_TOPIC),
                shared=options[ATTR_SHARED],
                markdown=options[ATTR_MARKDOWN],
                inputs=options[ATTR_INPUTS],
                files=options.get(ATTR_FILES),
                links=options.get(ATTR_LINKS),
                priority=options.get(ATTR_PRIORITY),
                expires_in=options.get(ATTR_EXPIRES_IN),
                wait=False,
            )
        except HomeAssistantError as err:
            _LOGGER.error(err)

    async def async_send_task(
        self,
        *,
        message: str,
        title: str,
        topic: str | None,
        shared: bool,
        markdown: bool,
        inputs: list[dict[str, Any]],
        files: list[str] | None,
        links: list[str] | None,
        priority: int | None,
        expires_in: float | None,
        wait: bool,
    ) -> dict[str, Any]:
        """Send a task and return its id.

        With `wait` and something to answer, the first answer (or how the task
        ended without one) is returned as well. Every answer also fires the
        Home Assistant events.
        """
        if topic is not None and topic not in self.topics:
            raise ServiceValidationError(
                f"Add the topic {topic} to the Simplepush entry before sending to it"
            )

        task_inputs, action_lookup = _build_inputs(inputs)
        wait = wait and bool(task_inputs)
        if wait and expires_in is None:
            raise ServiceValidationError(
                "Set expires_in to wait for the answer to a task"
            )

        if files:
            await self._check_allowed(files)

        expires_at = None
        if expires_in is not None:
            expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

        send = partial(
            self._client.send_task,
            topic=topic,
            title=title,
            content=message,
            content_format=ContentFormat.MARKDOWN if markdown else None,
            shared=shared,
            inputs=task_inputs or None,
            links=links,
            files=files,
            priority=priority,
            auto_commit=True,
            expires_at=expires_at,
        )
        try:
            sent = await self.hass.async_add_executor_job(send)
        except ApiError as err:
            if err.status == 401:
                self._start_reauth()
            raise HomeAssistantError(f"Simplepush rejected the task: {err}") from err
        except (OSError, ValueError, TypeError) as err:
            raise HomeAssistantError(f"Failed to send the task: {err}") from err

        response: dict[str, Any] = (
            {"group_id": sent.group_id}
            if isinstance(sent, TaskGroup)
            else {"task_id": sent.task_id}
        )
        if not task_inputs:
            return response

        result = self.hass.loop.create_future() if wait else None
        self.hass.async_create_background_task(
            self._collect_answers(sent, action_lookup, result),
            name="simplepush task answers",
        )
        if result is None:
            return response
        return {**response, **await result}

    def _disallowed_files(self, files: list[str]) -> list[str]:
        """Files Home Assistant does not allow to be read from outside."""
        return [path for path in files if not self.hass.config.is_allowed_path(path)]

    async def _check_allowed(self, files: list[str]) -> None:
        """Refuse files outside the directories Home Assistant allows."""
        if blocked := await self.hass.async_add_executor_job(
            self._disallowed_files, files
        ):
            raise ServiceValidationError(
                "Files outside the allowed directories were not sent: "
                f"{', '.join(blocked)}. Add their directory to allowlist_external_dirs"
            )

    async def async_send_notification(
        self,
        *,
        message: str,
        title: str,
        topic: str | None,
        shared: bool,
        priority: int | None,
        image: str | None,
        audio: str | None,
        link: str | None,
        notification_input: dict[str, Any] | None,
        timeout: float | None,
        wait: bool,
    ) -> dict[str, Any]:
        """Send a notification and return its id.

        With `wait` and an input, the first answer within `timeout` seconds is
        returned as well. Every answer also fires the Home Assistant event.
        """
        if topic is not None and topic not in self.topics:
            raise ServiceValidationError(
                f"Add the topic {topic} to the Simplepush entry before sending to it"
            )

        sdk_input: NotificationInput | None = None
        action_lookup: dict[str, tuple[str, Any]] = {}
        if notification_input is not None:
            sdk_input, action_lookup = _build_notification_input(notification_input)
        wait = wait and sdk_input is not None
        if wait and timeout is None:
            raise ServiceValidationError(
                "Set timeout to wait for the answer to a notification"
            )

        local_media = [
            path
            for path in (image, audio)
            if path and not path.startswith(("http://", "https://"))
        ]
        if local_media:
            await self._check_allowed(local_media)

        send = partial(
            self._client.send_notification,
            topic=topic,
            title=title,
            content=message,
            input=sdk_input,
            image=image,
            audio=audio,
            link=link,
            priority=priority,
            shared=shared,
        )
        try:
            sent = await self.hass.async_add_executor_job(send)
        except ApiError as err:
            if err.status == 401:
                self._start_reauth()
            raise HomeAssistantError(
                f"Simplepush rejected the notification: {err}"
            ) from err
        except (OSError, ValueError, TypeError) as err:
            raise HomeAssistantError(f"Failed to send the notification: {err}") from err

        response: dict[str, Any] = (
            {"group_id": sent.group_id}
            if isinstance(sent, NotificationGroup)
            else {"notification_id": sent.notification_id}
        )
        if sdk_input is None:
            return response

        result = self.hass.loop.create_future() if wait else None
        self.hass.async_create_background_task(
            self._collect_notification_answers(sent, action_lookup, result),
            name="simplepush notification answers",
        )
        if result is None:
            return response
        try:
            # A notification does not expire; an answer after the timeout
            # still fires the event.
            answer = await asyncio.wait_for(asyncio.shield(result), timeout)
        except TimeoutError:
            return {**response, "status": "pending"}
        return {**response, **answer}

    async def _collect_notification_answers(
        self,
        sent: Any,
        action_lookup: dict[str, tuple[str, Any]],
        result: asyncio.Future[dict[str, Any]] | None,
    ) -> None:
        """Fire a Home Assistant event for every answer to a notification.

        `result` receives the first answer.
        """
        try:
            async for event in sent.inputs(replay=True):
                item = event.item if isinstance(event, GroupNotification) else event
                if not isinstance(item, NotificationCompleted):
                    continue
                answer = self._notification_answer(sent, event, item, action_lookup)
                if result is not None and not result.done():
                    result.set_result(answer)
        except StreamError as err:
            if err.status_code == 401:
                self._start_reauth()
            _LOGGER.error("Lost the connection while waiting for answers: %s", err)
            if result is not None and not result.done():
                result.set_exception(
                    HomeAssistantError(
                        f"Lost the connection while waiting for the answer: {err}"
                    )
                )
        finally:
            if result is not None and not result.done():
                result.set_result({"status": "closed"})

    def _notification_answer(
        self,
        sent: Any,
        event: Any,
        item: NotificationCompleted,
        action_lookup: dict[str, tuple[str, Any]],
    ) -> dict[str, Any]:
        """Build the answer to a notification and fire its event."""
        answer: dict[str, Any] = {
            "status": "completed",
            "notification_id": item.notification_id,
            "completed_at": item.raw.created_at,
        }
        if isinstance(sent, NotificationGroup) and event.recipient:
            answer["recipient"] = event.recipient.name
            answer["recipient_id"] = event.recipient.public_id
        elif actor := item.raw.actor:
            answer["recipient"] = actor.get("name")
            answer["recipient_id"] = actor.get("publicId")

        match item.reply:
            case NotificationTextReply(value=value) if value is not None:
                answer["text"] = value
            case NotificationChoiceReply(selected_value=value) if value is not None:
                answer["choice"] = value
            case NotificationActionReply(selected_key=key):
                if key is None or (action := action_lookup.get(key)) is None:
                    _LOGGER.warning(
                        "Unknown action selected on notification %s",
                        item.notification_id,
                    )
                else:
                    answer["action"], action_id = action
                    if action_id is not None:
                        answer["action_id"] = action_id

        self.hass.bus.async_fire(EVENT_NOTIFICATION_COMPLETED, answer)
        return answer

    async def _collect_answers(
        self,
        sent: Any,
        action_lookup: dict[str, tuple[str, Any]],
        result: asyncio.Future[dict[str, Any]] | None,
    ) -> None:
        """Fire Home Assistant events for every answer until the task ends.

        `result` receives the first answer, or how the task ended without one.
        """
        status = "closed"
        try:
            async for event in sent.inputs(replay=True):
                item = event.item if isinstance(event, GroupInput) else event
                if isinstance(item, TaskCompleted):
                    answer = await self._answer(sent, event, item, action_lookup)
                    if result is not None and not result.done():
                        result.set_result(answer)
                elif (terminal := _TERMINAL_STATUS.get(type(item))) is not None:
                    status = terminal
        except StreamError as err:
            if err.status_code == 401:
                self._start_reauth()
            _LOGGER.error("Lost the connection while waiting for answers: %s", err)
            if result is not None and not result.done():
                result.set_exception(
                    HomeAssistantError(
                        f"Lost the connection while waiting for the answer: {err}"
                    )
                )
        finally:
            if result is not None and not result.done():
                result.set_result({"status": status})

    async def _answer(
        self,
        sent: Any,
        event: Any,
        item: TaskCompleted,
        action_lookup: dict[str, tuple[str, Any]],
    ) -> dict[str, Any]:
        """Build the answer of a completed task and fire its events."""
        answer: dict[str, Any] = {
            "status": "completed",
            "task_id": item.task_id,
            "completed_at": item.raw.created_at,
        }
        if isinstance(sent, TaskGroup) and event.recipient:
            answer["recipient"] = event.recipient.name
            answer["recipient_id"] = event.recipient.public_id
        elif actor := item.raw.actor:
            # Without a copy per recipient, the answer names who gave it.
            answer["recipient"] = actor.get("name")
            answer["recipient_id"] = actor.get("publicId")

        for upload in item.uploads:
            if isinstance(upload, VoiceUpload):
                answer.update(
                    await self._save_file("simplepush/tasks", upload, "voice")
                )
                if upload.duration_seconds is not None:
                    answer["voice_duration"] = upload.duration_seconds
                continue
            if isinstance(upload, LocationUpload):
                if (location := upload.location) is not None:
                    for key in ("latitude", "longitude", "accuracy"):
                        if (value := getattr(location, key)) is not None:
                            answer[key] = value
                continue
            if isinstance(upload, FileUpload):
                answer.update(await self._save_file("simplepush/tasks", upload, "file"))
                continue
            if isinstance(upload, SliderUpload):
                if upload.value is not None:
                    answer["slider"] = upload.value
                continue
            if isinstance(upload, ChoiceUpload):
                if upload.value is not None:
                    answer["choice"] = upload.value
                continue
            if isinstance(upload, MultiChoiceUpload):
                answer["choices"] = upload.values
                continue
            if isinstance(upload, PhotoUpload):
                answer.update(
                    await self._save_file("simplepush/tasks", upload, "photo")
                )
                continue
            if isinstance(upload, TextUpload):
                if upload.value is not None:
                    answer["text"] = upload.value
                continue
            if not isinstance(upload, ActionUpload):
                continue
            if upload.key is None or (action := action_lookup.get(upload.key)) is None:
                _LOGGER.warning("Unknown action selected on task %s", item.task_id)
                continue
            label, action_id = action
            answer["action"] = label
            if action_id is not None:
                answer["action_id"] = action_id

        if "action" in answer:
            payload: dict[str, Any] = {
                "action_selected": answer["action"],
                "action_selected_at": answer["completed_at"],
                "task_id": item.task_id,
            }
            if "action_id" in answer:
                payload["id"] = answer["action_id"]
            if "recipient" in answer:
                payload["recipient"] = answer["recipient"]
                payload["recipient_id"] = answer["recipient_id"]
            self.hass.bus.async_fire(EVENT_ACTION_TRIGGERED, payload)

        self.hass.bus.async_fire(EVENT_TASK_COMPLETED, answer)
        return answer

    def _media_folder(self) -> tuple[Path, bool]:
        """Return the media folder for downloads and whether it is the local one."""
        if local := self.hass.config.media_dirs.get("local"):
            return Path(local), True
        return Path(self.hass.config.path("media")), False

    async def _save_file(self, folder: str, upload: Any, key: str) -> dict[str, str]:
        """Download a photo, file or audio clip into `folder` of the media folder.

        Returns its file path under `key`, and its media source id when it is in
        the local media folder, or nothing when the download failed.
        """
        try:
            data = await upload.read()
        except (ApiError, DownloadError, OSError) as err:
            if (isinstance(err, ApiError) and err.status == 401) or (
                isinstance(err, DownloadError) and err.status_code == 401
            ):
                self._start_reauth()
            _LOGGER.error("Failed to download the %s %s: %s", key, upload.id, err)
            return {}

        base, local = self._media_folder()

        def write() -> Path:
            suffix = _extension(upload.content_type, upload.filename)
            path = base / folder / f"{upload.id}{suffix}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return path

        try:
            path = await self.hass.async_add_executor_job(write)
        except OSError as err:
            _LOGGER.error("Failed to save the %s %s: %s", key, upload.id, err)
            return {}

        saved = {key: str(path)}
        if local:
            saved[f"{key}_media_content_id"] = (
                f"media-source://media_source/local/{folder}/{path.name}"
            )
        return saved

    async def _async_delete_old_files(self, _now: datetime | None = None) -> None:
        """Delete downloads older than the configured number of hours."""
        assert self._delete_after is not None
        base, _ = self._media_folder()
        await self.hass.async_add_executor_job(
            _delete_old_files, base / "simplepush", self._delete_after * 3600
        )

    async def _listen_submissions(self) -> None:
        """Fire a Home Assistant event for every submission.

        The client reconnects on its own and resumes where it left off, so only
        a failure that won't go away ends the stream.
        """
        while True:
            try:
                # Building the stream fetches the password salt over HTTP.
                submissions = await self.hass.async_add_executor_job(
                    self._client.submissions
                )
                break
            except ApiError as err:
                if 400 <= err.status < 500:
                    if err.status == 401:
                        self._start_reauth()
                    _LOGGER.error("Can't listen for submissions: %s", err)
                    return
                failure: Exception = err
            except OSError as err:
                failure = err
            _LOGGER.warning(
                "Failed to start listening for submissions, retrying in %s seconds: %s",
                _SUBMISSIONS_RETRY_SECONDS,
                failure,
            )
            await asyncio.sleep(_SUBMISSIONS_RETRY_SECONDS)

        try:
            async for submission in submissions:
                await self._submission_received(submission)
        except StreamError as err:
            if err.status_code == 401:
                self._start_reauth()
            _LOGGER.error("Stopped listening for submissions: %s", err)

    async def _submission_received(self, submission: Submission) -> None:
        """Download the files of a submission and fire its event."""
        data: dict[str, Any] = {
            "submission_id": submission.id,
            "submitted_at": submission.created_at,
        }
        if actor := submission.raw.actor:
            data["sender"] = actor.get("name")
            data["sender_id"] = actor.get("publicId")
        if submission.body is not None and submission.body.text is not None:
            data["text"] = submission.body.text
        if (location := submission.location) is not None:
            for key in ("latitude", "longitude", "accuracy"):
                if (value := getattr(location, key)) is not None:
                    data[key] = value

        folder = "simplepush/submissions"
        for key, upload in (
            ("photo", submission.photo),
            ("file", submission.file),
            ("audio", submission.audio),
        ):
            if upload is not None:
                data.update(await self._save_file(folder, upload, key))

        self.hass.bus.async_fire(EVENT_SUBMISSION_RECEIVED, data)
