"""Simplepush notification service."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from functools import partial
import logging
import mimetypes
from pathlib import Path
from typing import Any

from simplepush import (
    Action,
    ActionsInput,
    ActionUpload,
    ApiError,
    ContentFormat,
    DownloadError,
    GroupInput,
    PhotoInput,
    PhotoUpload,
    StreamError,
    TaskCanceled,
    TaskCompleted,
    TaskDeclined,
    TaskDeleted,
    TaskExpired,
    TaskGroup,
    TextInput,
    TextUpload,
)
import voluptuous as vol

from homeassistant.components.notify import (
    ATTR_DATA,
    ATTR_TITLE,
    ATTR_TITLE_DEFAULT,
    BaseNotificationService,
)
from homeassistant.const import CONF_API_TOKEN, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
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
    CONF_ENTRY_ID,
    CONF_TOPICS,
    DOMAIN,
    EVENT_ACTION_TRIGGERED,
    EVENT_TASK_COMPLETED,
)
from .services import NOTIFY_DATA_SCHEMA

_LOGGER = logging.getLogger(__name__)

# Service data keys of the old device-key API that no longer exist.
_REMOVED_DATA_KEYS = ("action_timeout", "actions", "attachments", "event")

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
    return task_inputs, action_lookup


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
        self.topics: dict[str, str | None] = config[CONF_TOPICS]
        self._client = create_client(
            config[CONF_API_TOKEN], config.get(CONF_PASSWORD), self.topics
        )

    async def async_close(self) -> None:
        """Close the client's event connection."""
        await self._client.aclose()

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

        if files and (
            blocked := await self.hass.async_add_executor_job(
                self._disallowed_files, files
            )
        ):
            raise ServiceValidationError(
                "Files outside the allowed directories were not sent: "
                f"{', '.join(blocked)}. Add their directory to allowlist_external_dirs"
            )

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
            if isinstance(upload, PhotoUpload):
                answer.update(await self._save_photo(item.task_id, upload))
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

    async def _save_photo(
        self, task_id: str | None, upload: PhotoUpload
    ) -> dict[str, str]:
        """Download a photo answer into the media folder.

        Returns its file path, and its media source id when it is in the local
        media folder, or nothing when the download failed.
        """
        try:
            data = await upload.read()
        except (ApiError, DownloadError, OSError) as err:
            _LOGGER.error("Failed to download the photo of task %s: %s", task_id, err)
            return {}

        local = self.hass.config.media_dirs.get("local")
        relative = f"simplepush/tasks/{upload.id}"

        def write() -> str:
            suffix = _extension(upload.content_type, upload.filename)
            path = Path(local or self.hass.config.path("media"), relative + suffix)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return str(path)

        try:
            path = await self.hass.async_add_executor_job(write)
        except OSError as err:
            _LOGGER.error("Failed to save the photo of task %s: %s", task_id, err)
            return {}

        photo = {"photo": path}
        if local:
            name = Path(path).name
            photo["photo_media_content_id"] = (
                f"media-source://media_source/local/simplepush/tasks/{name}"
            )
        return photo
