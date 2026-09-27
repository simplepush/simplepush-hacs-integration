"""Simplepush notification service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import partial
import logging
from typing import Any

from simplepush import (
    Action,
    ActionsInput,
    ActionUpload,
    ApiError,
    GroupInput,
    StreamError,
    TaskCompleted,
    TaskGroup,
)

from homeassistant.components.notify import (
    ATTR_DATA,
    ATTR_TITLE,
    ATTR_TITLE_DEFAULT,
    BaseNotificationService,
)
from homeassistant.const import CONF_API_TOKEN, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .client import create_client
from .const import (
    ATTR_ACTIONS,
    ATTR_EXPIRES_IN,
    ATTR_FILES,
    ATTR_LINKS,
    ATTR_PRIORITY,
    ATTR_TOPIC,
    CONF_ENTRY_ID,
    CONF_TOPICS,
    DOMAIN,
    EVENT_ACTION_TRIGGERED,
)

_LOGGER = logging.getLogger(__name__)

# Service data keys of the old device-key API that no longer exist.
_REMOVED_DATA_KEYS = ("action_timeout", "attachments", "event")


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
    actions_data: Any,
) -> tuple[ActionsInput | None, dict[str, tuple[str, Any]]]:
    """Turn the `actions` service data into a task input.

    Returns the input and a map from the generated action key to the action's
    label and optional id, used to build the Home Assistant event.
    """
    if not isinstance(actions_data, list) or not actions_data:
        return None, {}

    actions: list[Action] = []
    lookup: dict[str, tuple[str, Any]] = {}
    for entry in actions_data:
        if not isinstance(entry, dict) or not entry.get("action"):
            _LOGGER.error("Action format is incorrect: %s", entry)
            return None, {}
        if "url" in entry:
            _LOGGER.error(
                "Actions with a url are no longer supported. Use the links field "
                "of the notification instead"
            )
            return None, {}
        key = str(len(actions))
        label = str(entry["action"])
        actions.append(Action(key=key, label=label, style=entry.get("style")))
        lookup[key] = (label, entry.get("id"))

    return ActionsInput(actions=actions), lookup


def _string_list(value: Any) -> list[str] | None:
    """Accept a single string or a list of strings."""
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _priority(value: Any) -> int | None:
    """Priority level 1 to 5, or None for the default."""
    if value is None:
        return None
    try:
        level = int(value)
    except (ValueError, TypeError):
        level = 0
    if not 1 <= level <= 5:
        raise ValueError(f"Priority must be a number from 1 to 5: {value}")
    return level


def _expires_at(value: Any) -> datetime | None:
    """Deadline `value` seconds from now, or None when not set."""
    if value is None:
        return None
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        seconds = 0
    if seconds <= 0:
        raise ValueError(f"expires_in must be a positive number of seconds: {value}")
    return datetime.now(UTC) + timedelta(seconds=seconds)


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
        title = kwargs.get(ATTR_TITLE, ATTR_TITLE_DEFAULT)
        data: dict[str, Any] = kwargs.get(ATTR_DATA) or {}

        for key in _REMOVED_DATA_KEYS:
            if key in data:
                _LOGGER.warning(
                    "The %s field is no longer supported and was ignored", key
                )

        topic = data.get(ATTR_TOPIC)
        if topic is not None and topic not in self.topics:
            _LOGGER.error(
                "Add the topic %s to the Simplepush entry before sending to it", topic
            )
            return

        action_input, action_lookup = _build_actions(data.get(ATTR_ACTIONS))
        if data.get(ATTR_ACTIONS) and action_input is None:
            return

        try:
            priority = _priority(data.get(ATTR_PRIORITY))
            expires_at = _expires_at(data.get(ATTR_EXPIRES_IN))
        except ValueError as err:
            _LOGGER.error(err)
            return

        files = _string_list(data.get(ATTR_FILES))
        if files and (
            blocked := await self.hass.async_add_executor_job(
                self._disallowed_files, files
            )
        ):
            _LOGGER.error(
                "Files outside the allowed directories were not sent: %s. "
                "Add their directory to allowlist_external_dirs",
                ", ".join(blocked),
            )
            return

        send = partial(
            self._client.send_task,
            topic=topic,
            title=title,
            content=message,
            inputs=[action_input] if action_input else None,
            links=_string_list(data.get(ATTR_LINKS)),
            files=files,
            priority=priority,
            auto_commit=True,
            expires_at=expires_at,
        )
        try:
            sent = await self.hass.async_add_executor_job(send)
        except ApiError as err:
            _LOGGER.error("Simplepush rejected the task: %s", err)
            return
        except (OSError, ValueError, TypeError) as err:
            _LOGGER.error("Failed to send the task: %s", err)
            return

        if action_input is None:
            return

        self.hass.async_create_background_task(
            self._collect_actions(sent, action_lookup),
            name="simplepush action feedback",
        )

    def _disallowed_files(self, files: list[str]) -> list[str]:
        """Files Home Assistant does not allow to be read from outside."""
        return [path for path in files if not self.hass.config.is_allowed_path(path)]

    async def _collect_actions(
        self,
        sent: Any,
        action_lookup: dict[str, tuple[str, Any]],
    ) -> None:
        """Fire a Home Assistant event for every selected action."""
        try:
            async for event in sent.inputs():
                item = event.item if isinstance(event, GroupInput) else event
                if not isinstance(item, TaskCompleted):
                    continue

                for upload in item.uploads:
                    if not isinstance(upload, ActionUpload):
                        continue
                    if (
                        upload.key is None
                        or (action := action_lookup.get(upload.key)) is None
                    ):
                        _LOGGER.warning(
                            "Unknown action selected on task %s", item.task_id
                        )
                        continue

                    label, action_id = action
                    payload: dict[str, Any] = {
                        "action_selected": label,
                        "action_selected_at": item.raw.created_at,
                        "task_id": item.task_id,
                    }
                    if action_id is not None:
                        payload["id"] = action_id
                    if isinstance(sent, TaskGroup) and event.recipient:
                        payload["recipient"] = event.recipient.name
                        payload["recipient_id"] = event.recipient.public_id

                    self.hass.bus.async_fire(EVENT_ACTION_TRIGGERED, payload)
        except StreamError as err:
            _LOGGER.error("Lost the connection while waiting for actions: %s", err)
