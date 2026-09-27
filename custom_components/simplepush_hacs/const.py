"""Constants for the simplepush integration."""

from typing import Final

DOMAIN: Final = "simplepush_hacs"
DEFAULT_NAME: Final = "Simplepush"
DATA_HASS_CONFIG: Final = "simplepush_hass_config"

CONF_TOPIC: Final = "topic"
CONF_TOPICS: Final = "topics"
CONF_ENTRY_ID: Final = "entry_id"

SUBENTRY_TOPIC: Final = "topic"

ATTR_AUDIO: Final = "audio"
ATTR_EXPIRES_IN: Final = "expires_in"
ATTR_FILES: Final = "files"
ATTR_IMAGE: Final = "image"
ATTR_INPUT: Final = "input"
ATTR_INPUTS: Final = "inputs"
ATTR_LINK: Final = "link"
ATTR_LINKS: Final = "links"
ATTR_MARKDOWN: Final = "markdown"
ATTR_PRIORITY: Final = "priority"
ATTR_SHARED: Final = "shared"
ATTR_TIMEOUT: Final = "timeout"
ATTR_TOPIC: Final = "topic"

SERVICE_SEND_NOTIFICATION: Final = "send_notification"
SERVICE_SEND_TASK: Final = "send_task"

EVENT_ACTION_TRIGGERED: Final = "simplepush_action_triggered_event"
EVENT_NOTIFICATION_COMPLETED: Final = "simplepush_notification_completed_event"
EVENT_TASK_COMPLETED: Final = "simplepush_task_completed_event"
