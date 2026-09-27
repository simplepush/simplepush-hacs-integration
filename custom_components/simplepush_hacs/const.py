"""Constants for the simplepush integration."""

from typing import Final

DOMAIN: Final = "simplepush_hacs"
DEFAULT_NAME: Final = "Simplepush"
DATA_HASS_CONFIG: Final = "simplepush_hass_config"

CONF_TOPIC: Final = "topic"
CONF_TOPICS: Final = "topics"
CONF_ENTRY_ID: Final = "entry_id"

SUBENTRY_TOPIC: Final = "topic"

ATTR_EXPIRES_IN: Final = "expires_in"
ATTR_FILES: Final = "files"
ATTR_INPUTS: Final = "inputs"
ATTR_LINKS: Final = "links"
ATTR_MARKDOWN: Final = "markdown"
ATTR_PRIORITY: Final = "priority"
ATTR_SHARED: Final = "shared"
ATTR_TOPIC: Final = "topic"

SERVICE_SEND_TASK: Final = "send_task"

EVENT_ACTION_TRIGGERED: Final = "simplepush_action_triggered_event"
